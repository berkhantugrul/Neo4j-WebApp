import os
import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from typing import Any

# 🔌 MCP BAĞLANTI PROTOKOLLERİ
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai.types.chat import ChatCompletionMessageParam

router = APIRouter(prefix="/llm", tags=["LLM & MCP Gateway"])

class ChatRequest(BaseModel):
    prompt: str

# 🏢 İÇ AĞ ALTYAPI ADRESLERİ
INTERNAL_GPU_URL = "http://10.20.30.40:8000/v1"  
INTERNAL_LLM_MODEL = "meta-llama-3-8b-instruct"  

ai_client = AsyncOpenAI(base_url=INTERNAL_GPU_URL, api_key="enterprise-on-prem-key")

async def enterprise_agent_engine(user_prompt: str):
    server_script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "f5_server.py"))
    
    server_params = StdioServerParameters(
        command="python",
        args=[server_script_path]
    )
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            
            await mcp_session.initialize()
            available_tools_rpc: Any = await mcp_session.list_tools()
            
            yield f"data: {json.dumps({'status': 'connected'})}\n\n"
            await asyncio.sleep(0.1)
            
            # ==============================================================================
            # 🛡️ KURŞUN GEÇİRMEZ ŞEMA DÖNÜŞTÜRÜCÜ (DIREKT TIP KONTROLÜ)
            # ==============================================================================
            llm_formatted_tools = []
            if available_tools_rpc and hasattr(available_tools_rpc, "tools"):
                for t in available_tools_rpc.tools:
                    t_name = getattr(t, "name", "unknown")
                    t_desc = getattr(t, "description", "F5 BIG-IP Tool")
                    t_schema = getattr(t, "input_schema", getattr(t, "inputSchema", {}))
                    
                    # 🎯 Line 56 Hatasını Kökten Çözen Güvenli Sözlük Dönüşümü:
                    schema_dict = {}
                    if isinstance(t_schema, dict):
                        schema_dict = t_schema
                    elif hasattr(t_schema, "model_dump") and callable(getattr(t_schema, "model_dump", None)):
                        schema_dict = t_schema.model_dump()
                    elif hasattr(t_schema, "dict") and callable(getattr(t_schema, "dict", None)):
                        schema_dict = t_schema.dict()
                    
                    # Saf OpenAI parametre yapısını izole ediyoruz
                    properties_block = schema_dict.get("properties", {}) if isinstance(schema_dict, dict) else {}
                    required_block = schema_dict.get("required", []) if isinstance(schema_dict, dict) else []
                    
                    clean_parameters = {
                        "type": "object",
                        "properties": properties_block,
                        "required": required_block
                    }
                    
                    llm_formatted_tools.append({
                        "type": "function",
                        "function": {
                            "name": str(t_name).strip(),
                            "description": str(t_desc).strip(),
                            "parameters": clean_parameters
                        }
                    })

            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": "Sen kurumsal bir F5 BIG-IP NetOps uzman yapay zeka asistanısın. Elindeki araçları kullanarak F5 cihazından canlı veri çekebilirsin."},
                {"role": "user", "content": user_prompt}
            ]
            
            native_tools_failed = False
            response_message: Any = None
            tool_calls = None
            
            # 🧠 NATIVE TOOL CALLING DENEMESİ
            try:
                first_response = await ai_client.chat.completions.create(
                    model=INTERNAL_LLM_MODEL,
                    messages=messages,
                    tools=llm_formatted_tools if llm_formatted_tools else None,
                    tool_choice="auto" if llm_formatted_tools else None
                )
                response_message = first_response.choices[0].message
                tool_calls = getattr(response_message, "tool_calls", None)
                
            except Exception:
                # Altyapı şema uyuşmazlığından hata verirse burası otonom koruma sağlar
                native_tools_failed = True

            # ==============================================================================
            # 🚀 FALLBACK MODE: METİN PROTOKOLÜ TAVSİYESİ
            # ==============================================================================
            if native_tools_failed or tool_calls is None:
                yield f"data: {json.dumps({'token': '⚠️ [vLLM Koruması] Şema bypass edildi. Metin Protokolü (Text-Protocol) üzerinden otonom akış başlatılıyor...\n\n'})}\n\n"
                await asyncio.sleep(0.2)
                
                tools_text_desc = ""
                for tool in llm_formatted_tools:
                    tools_text_desc += f"- Araç Adı: {tool['function']['name']}\nAçıklama: {tool['function']['description']}\nParametre Yapısı: {json.dumps(tool['function']['parameters'])}\n\n"
                
                fallback_system_prompt = (
                    "Sen kurumsal bir F5 BIG-IP NetOps uzman yapay zeka asistanısın. "
                    "Kullanıcının canlı F5 ağ verisi isteklerini yerine getirmek için aşağıdaki F5 araçlarından uygun olanını seçmeli "
                    "ve yanıtında BAŞKA HİÇBİR ŞEY YAZMADAN YALNIZCA şu JSON formatında bir çağrı bırakmalısın:\n"
                    "```json\n"
                    "{\n"
                    "  \"TOOL_REQUEST\": {\n"
                    "    \"name\": \"fonksiyon_adi\",\n"
                    "    \"arguments\": {}\n"
                    "  }\n"
                    "}\n"
                    "```\n"
                    f"KULLANABİLECEĞİN CANLI F5 ENVENTER FONKSİYONLARI:\n{tools_text_desc}"
                )
                
                fallback_messages = [
                    {"role": "system", "content": fallback_system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
                
                fallback_res = await ai_client.chat.completions.create(
                    model=INTERNAL_LLM_MODEL,
                    messages=fallback_messages # type: ignore
                )
                fallback_text = fallback_res.choices[0].message.content or ""
                
                if "TOOL_REQUEST" in fallback_text:
                    yield f"data: {json.dumps({'token': '🔄 [Metin Protokolü] F5 MCP aracı tetikleniyor...\n\n'})}\n\n"
                    await asyncio.sleep(0.1)
                    
                    try:
                        start_idx = fallback_text.find("{")
                        end_idx = fallback_text.rfind("}") + 1
                        json_str = fallback_text[start_idx:end_idx]
                        parsed_request = json.loads(json_str)
                        
                        t_info = parsed_request.get("TOOL_REQUEST", {})
                        f_name = t_info.get("name")
                        f_args = t_info.get("arguments", {})
                        
                        mcp_output = await mcp_session.call_tool(f_name, arguments=f_args)
                        raw_f5_text = mcp_output.content[0].text
                        
                        fallback_messages.append({"role": "assistant", "content": fallback_text}) # type: ignore
                        fallback_messages.append({
                            "role": "user", 
                            "content": f"F5 Cihazından dönen GERÇEK VERİ ŞUDUR:\n\n{raw_f5_text}\n\nLütfen bu veriyi kullanarak kullanıcıya nihai analizi sun."
                        }) # type: ignore
                        
                        final_stream = await ai_client.chat.completions.create(
                            model=INTERNAL_LLM_MODEL,
                            messages=fallback_messages, # type: ignore
                            stream=True
                        )
                        async for chunk in final_stream:
                            try:
                                token = chunk.choices[0].delta.content or "" # type: ignore
                                if token: yield f"data: {json.dumps({'token': token})}\n\n"
                            except Exception: pass
                    except Exception as inner_e:
                        yield f"data: {json.dumps({'token': f'❌ [Ayrıştırma Hatası]: {str(inner_e)}'})}\n\n"
                else:
                    yield f"data: {json.dumps({'token': fallback_text})}\n\n"
                
                yield f"data: {json.dumps({'status': 'done'})}\n\n"
                return

            # ==============================================================================
            # 🚀 SENARYO B: NORMAL NATIVE AKIŞ
            # ==============================================================================
            if tool_calls is not None:
                yield f"data: {json.dumps({'token': '🔄 [Native Mod] F5 MCP aracı tetikleniyor...\n\n'})}\n\n"
                assistant_tool_calls_structure = []
                tools_to_execute = []
                
                for raw_call in tool_calls:
                    call_obj: Any = raw_call
                    if not call_obj or (hasattr(call_obj, "__len__") and len(call_obj) == 0): continue
                    if isinstance(call_obj, tuple):
                        call_obj = call_obj[1] if len(call_obj) > 1 else call_obj[0]
                        
                    if isinstance(call_obj, dict):
                        call_id = call_obj.get("id", "call_default")
                        func_block = call_obj.get("function", {})
                    else:
                        call_id = getattr(call_obj, "id", "call_default")
                        func_block = getattr(call_obj, "function", {})
                        
                    function_name = func_block.get("name", getattr(func_block, "name", "unknown"))
                    raw_args = func_block.get("arguments", getattr(func_block, "arguments", "{}"))
                        
                    try: function_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception: function_args = {}
                        
                    assistant_tool_calls_structure.append({
                        "id": str(call_id),
                        "type": "function",
                        "function": { "name": str(function_name), "arguments": json.dumps(function_args) }
                    })
                    tools_to_execute.append((function_name, function_args, call_id))
                
                if not tools_to_execute:
                    yield f"data: {json.dumps({'token': getattr(response_message, 'content', '') or ''})}\n\n"
                    yield f"data: {json.dumps({'status': 'done'})}\n\n"
                    return

                messages.append({"role": "assistant", "content": getattr(response_message, "content", None), "tool_calls": assistant_tool_calls_structure}) # type: ignore
                
                for f_name, f_args, c_id in tools_to_execute:
                    mcp_output = await mcp_session.call_tool(f_name, arguments=f_args)
                    raw_f5_text = mcp_output.content[0].text
                    messages.append({"role": "tool", "tool_call_id": str(c_id), "content": str(raw_f5_text)}) # type: ignore
                
                final_stream = await ai_client.chat.completions.create(model=INTERNAL_LLM_MODEL, messages=messages, stream=True)
                async for chunk in final_stream:
                    try:
                        token = chunk.choices[0].delta.content or "" # type: ignore
                        if token: yield f"data: {json.dumps({'token': token})}\n\n"
                    except Exception: pass
            else:
                yield f"data: {json.dumps({'token': getattr(response_message, 'content', '') or ''})}\n\n"
                
            yield f"data: {json.dumps({'status': 'done'})}\n\n"

@router.post("/chat/stream")
async def stream_chat_response(request: ChatRequest):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt boş olamaz.")
    return StreamingResponse(enterprise_agent_engine(request.prompt), media_type="text/event-stream")
