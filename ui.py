import streamlit as st
from neo4j import GraphDatabase, basic_auth
from neo4j.exceptions import ServiceUnavailable, AuthError
from neo4j_processes import *
import pandas as pd
from streamlit_option_menu import option_menu
from pyvis.network import Network
import streamlit.components.v1 as components
import matplotlib.pyplot as plt
import networkx as nx
import plotly.express as px
import joblib, os
import networkx as nx

# Bağlantı bilgileri
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "password"

st.set_page_config(
    page_title="Neo4j Movie DB App",
    page_icon="https://st2.depositphotos.com/1062085/6772/v/950/depositphotos_67729517-stock-illustration-data-visualization-icon-concept.jpg",
    layout="wide",
    initial_sidebar_state="expanded",
)

@st.cache_resource
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=basic_auth(NEO4J_USER, NEO4J_PASS))


MODEL_FILES  = {
    "RandomForest": "RandomForest.pkl",
    "Ridge":        "Ridge.pkl",
    "KNN":          "KNN.pkl",
}
USER_ENC_FILE  = "user_encoder.pkl"
MOVIE_ENC_FILE = "movie_encoder.pkl"

def load_model():
    # 1) Modeller ve encoder dosyaları var mı?
    files_ok = all(os.path.exists(p) for p in MODEL_FILES.values()) \
               and os.path.exists(USER_ENC_FILE) \
               and os.path.exists(MOVIE_ENC_FILE)
    if files_ok:
        models = {n: joblib.load(p) for n, p in MODEL_FILES.items()}
        user_enc  = joblib.load(USER_ENC_FILE)
        movie_enc = joblib.load(MOVIE_ENC_FILE)
        return models, user_enc, movie_enc

    # 2) Eksikse yeniden eğit
    df = getAllData()
    return encodeTrainTest(df)
    
def check_neo4j_connection():
    try:
        driver = get_driver()
        with driver.session() as session:
            session.run("RETURN 1")
        return True
    except (ServiceUnavailable, AuthError, Exception):
        return False

def get_graph_data(selected_types):
    driver = get_driver()
    with driver.session() as session:

        # Filtreli ilişkili düğümler
        if selected_types:
            query = f"""
            MATCH (n)-[r]->(m)
            WHERE ANY(lbl IN labels(n) WHERE lbl IN $types)
               OR ANY(lbl IN labels(m) WHERE lbl IN $types)
            RETURN n, type(r) AS rel_type, m
            """
            rel_result = session.run(query, types=selected_types)
        else:
            rel_result = session.run("MATCH (n)-[r]->(m) RETURN n, type(r) AS rel_type, m")

        # Filtreli ilişkisiz düğümler
        if selected_types:
            solo_query = """
            MATCH (n)
            WHERE NOT (n)--()
              AND ANY(lbl IN labels(n) WHERE lbl IN $types)
            RETURN n
            """
            solo_result = session.run(solo_query, types=selected_types)
        else:
            solo_result = session.run("MATCH (n) WHERE NOT (n)--() RETURN n")

        return {
            "rel_records": list(rel_result),
            "solo_nodes": list(solo_result)
        }


def draw_network(graph_data, selected_types):
    rel_counter = 0
    node_counter = 0
    from pyvis.network import Network

    rel_records = graph_data["rel_records"]
    solo_nodes = graph_data["solo_nodes"]

    net = Network(height="550px", width="100%", bgcolor="#ffffff", font_color="black", notebook=False, directed=True)
    net.force_atlas_2based()
    added_nodes = set()

    def get_color(labels):
        if "Person" in labels:
            return "#FF6B6B"
        elif "Movie" in labels:
            return "#4D96FF"
        elif "Genre" in labels:
            return "#FFD93D"
        elif "User" in labels:
            return "#6BCB77"
        else:
            return "#D3D3D3"

    def should_add(labels):
        return not selected_types or any(lbl in selected_types for lbl in labels)

    def add_node_if_needed(node):
        node_id = node.element_id
        if node_id not in added_nodes:
            labels = list(node.labels)
            if should_add(labels):
                label = node.get("name") or node.get("title") or node.get("username")
                tooltip = "\n".join([f"{k}: {v}" for k, v in node.items()])
                net.add_node(node_id, label=label, title=tooltip, color=get_color(labels))
                added_nodes.add(node_id)

    # Önce tüm geçerli düğümleri ekle (ilişkili ve ilişkisiz)
    all_nodes = [rec["n"] for rec in rel_records] + [rec["m"] for rec in rel_records] + [rec["n"] for rec in solo_nodes]
    for node in all_nodes:
        node_counter += 1
        add_node_if_needed(node)
        if node_counter >= 100:
            break

    # Şimdi sadece ilişkili düğümler arasında kenar ekle
    for record in rel_records:
        rel_counter += 1
        n_id = record["n"].element_id
        m_id = record["m"].element_id
        if n_id in added_nodes and m_id in added_nodes:
            net.add_edge(n_id, m_id, label=record["rel_type"])
        if rel_counter >= 500:
            break

    return net




def show_graph(selected_types):
    records = get_graph_data(selected_types)
    net = draw_network(records, selected_types)
    net.save_graph("graph.html")
    net.write_html("graph.html")  # same as save_graph

    try:
        st.info("To save the graph as an image, right-click on the graph area and choose 'Save As'.")

    except Exception as e:
        st.warning(f"PNG export failed: {e}")

    with open("graph.html", "r", encoding="utf-8") as f:
        html = f.read()
    components.html(html, height=650, scrolling=True)


def show_statistics():
    driver = get_driver()
    with driver.session() as session:
        film_count = session.run("MATCH (m:Movie) RETURN count(m) AS count").single()["count"]
        person_count = session.run("MATCH (p:Person) RETURN count(p) AS count").single()["count"]
        user_count = session.run("MATCH (u:User) RETURN count(u) AS count").single()["count"]
        genre_count = session.run("MATCH (g:Genre) RETURN count(g) AS count").single()["count"]
        avg_rating = session.run("MATCH (:User)-[r:RATED]->() RETURN avg(r.score) AS avg").single()["avg"]
        total_rel = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Movies", film_count)
    col2.metric("Person", person_count)
    col3.metric("Avg. Rating", f"{avg_rating:.2f}" if avg_rating else "N/A")
    col4.metric("Total Relationships", total_rel)
    col5.metric("Users", user_count)
    col6.metric("Genres", genre_count)


def search_node(term):
    driver = get_driver()
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            WHERE toLower(n.name) CONTAINS toLower($term) OR toLower(n.title) CONTAINS toLower($term)
            RETURN labels(n) AS labels, n LIMIT 10
        """, term=term)
        return [r.data() for r in result]


def show_relationship_counts():
    driver = get_driver()
    with driver.session() as session:
        result = session.run("""
            MATCH (n)-[r]->()
            RETURN coalesce(n.name, n.title, "Unnamed Node") AS node, count(r) AS relation_count
            ORDER BY relation_count DESC LIMIT 10
        """)
        return pd.DataFrame([r.data() for r in result])


# Beyaz kutu: Neo4j bağlantı durumu
print("Connection status:", check_neo4j_connection())


if check_neo4j_connection() == True:

    # Menü seçim fonksiyonu
    def update_menu(choice):
        st.session_state.page = choice


    st.markdown(
        """
        <style>
        .stButton button {
            width: 100%;
            background-color: transparent; /* Green */
            border: 2px solid transparent; /* Green */
            color: black;
            padding: 10px 20px;
            text-align: center;
            border-radius: 10px;
            transition: all 0.3s ease; /* Smooth transition for hover effect */
        }
        .stButton button:hover {
            background-color: transparent; /* Light gray background on hover */
            border-color: #666666; /* Blue border on hover */
            color: #666666; /* Blue text on hover */
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


    # At the beginning, set the page to "home"
    # This will be used to determine which page to show in the sidebar
    if "page" not in st.session_state:
        st.session_state.page = "Home"


    with st.sidebar:
        st.markdown("<h1 style='text-align: center; font-size: 22px; margin-bottom: 20px;'>Neo4j Movie App Menu</h1>", unsafe_allow_html=True)

        # Özel kutu tasarımı (HTML+CSS)
        st.markdown("""
            <div style="padding: 15px; border-radius: 10px; background-color: #FFFFFF; border: 1px solid lightgray">
                <h4 style="margin-top: 0; color:black">📡 Neo4j DB Connection: </h4>
                <p style="color: %s; font-weight: bold;">%s</p>
            </div>
        """ % (
            "green" if check_neo4j_connection() else "red",
            "🟢 Connected" if check_neo4j_connection() else "🔴 Not Connected"
        ), unsafe_allow_html=True)


        selected = option_menu(
            menu_title=None,
            options=["Home", "Add Data", "Delete Data", "Explore / Visualize", "ML & Analysis", "About & Settings"],
            icons=["house", "plus-circle", "trash", "search", "graph-up-arrow", "gear"],
            menu_icon=None,
            default_index=0,
            orientation="vertical",
            key="page",
            styles={
                "container": {"background-color": "transparent", "margin-top": "20px", "width": "110%", "margin-left": "-10px"},
                "icon": {"color": "#000000", "font-size": "15px", "margin-right": "10px"},
                "nav-link": {"font-size": "18px", "--hover-color": "#f78b83"},
                "nav-link-selected": {"background-color": "#f78b83", "color": "#000000", "font-weight": "normal"},
            },
        )



    if st.session_state.page == "Home":
        st.markdown("<h1 style='text-align: left; font-size: 30px; '>Welcome to the Neo4j Movie DB App!</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 18px; margin-top: 30px '>&bull;  This app allows you to manage and visualize your Neo4j Movie database.</p>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 18px; font-weight: bold'>&bull;  In this project, the movie dataset and processes will be used.</p>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 18px;'>&bull;  Use the sidebar to navigate through the app.</p>", unsafe_allow_html=True)


    if st.session_state.page == "Add Data":
        st.markdown("<h1 style='text-align: left; font-size: 30px;'>Add Data to DB</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 18px;'>Use the form below to add data to your Neo4j database.</p>", unsafe_allow_html=True)

        tab1, tab2 = st.tabs(["Add by Selection", "Add by Query"])

        with tab1:

            # Add your form for adding data here
            # For example, you can use st.text_input() to get user input for adding a person, movie, etc.
            st.markdown("<p style='text-align: left; font-size: 17px;'>Select a option for adding data to database.</p>", unsafe_allow_html=True)

            option = st.selectbox(
                "Select an option",
                ("Add Person", "Add Movie & Genre", "Create Relationship"),
            )

            st.markdown("---")

            if option == "Add Person":

                st.markdown("<h3 style='text-align: left; font-size: 20px;'>Add Person</h3>", unsafe_allow_html=True)

                user_type = st.selectbox("Select Category", ["User", "Movie Person"])
                st.markdown("<p style='text-align: left; font-size: 17px;'>Select a person category.</p>", unsafe_allow_html=True)

                if user_type == "User":
                    st.markdown("<p style='text-align: left; font-size: 17px;'>The 'User' category will be created.</p>", unsafe_allow_html=True)

                    name = st.text_input("Enter the user's name")

                    if st.button("Add User"):
                        if not name:
                            st.warning("Please enter a name and age.")
                        else:
                            with get_driver() as driver:
                                with driver.session() as session:
                                    session.execute_write(add_user, name.strip())
                            st.success(f"{name} added successfully!")


                elif user_type == "Movie Person":

                    col1, col2 = st.columns(2)

                    with col1:
                        name = st.text_input("Enter the person's name")
                        age = st.number_input("Enter the person's age", min_value=0, max_value=120, value=25, step=1)

                    with col2:
                        roles = st.multiselect("Select one or more roles", ["Actor", "Director", "Producer"])
                        gender = st.selectbox("Select the gender", ["Male", "Female"])

                    ###### GUNCELLENECEK ######
                    if st.button("Add Person"):
                        if not name or not roles:
                            st.warning("Please enter a name and select at least one role.")
                        else:
                            with get_driver() as driver:
                                with driver.session() as session:
                                    session.execute_write(add_movie_person, name.strip(), age, gender, roles)
                            st.success(f"{name} added successfully!")


            elif option == "Add Movie & Genre":
                st.markdown("<h3 style='text-align: left; font-size: 20px;'>Add Movie & Genre</h3>", unsafe_allow_html=True)
                st.markdown("<p style='text-align: left; font-size: 17px;'>The 'IN_GENRE' relation will be created automatically between Movie and Genre.</p>", unsafe_allow_html=True)

                col1, col2, col3 = st.columns(3)

                with col1:
                    title = st.text_input("Enter the movie name")

                with col2:
                    year = st.number_input("Enter the release year", min_value=1900, max_value=2100, value=2025, step=1)

                with col3:
                    genres = st.multiselect("Select one or more genres", ["Action", "Comedy", "Drama", "Horror", "Sci-Fi", "Crime", "Romance", "Thriller", "Fantasy", "Adventure", "Documentary", "Animation", "Biography", "Family", "History", "War", "Western"])

                if st.button("Add Movie"):
                    if not title or not genres:
                        st.warning("Please enter title and select at least one genre.")
                    else:
                        with get_driver() as driver:
                            with driver.session() as session:
                                session.execute_write(add_movie_with_genres, title.strip(), year, genres)
                        st.success(f"Movie '{title}' added with genres: {', '.join(genres)}")


            elif option == "Create Relationship":
                st.markdown("<h3 style='text-align: left; font-size: 20px;'>Create Relationship</h3>", unsafe_allow_html=True)
                st.markdown("<p style='text-align: left; font-size: 17px;'>Select a person category as User or Movie Person.</p>", unsafe_allow_html=True)

                selected = st.selectbox("Select a Person", ["User", "Movie Person"])

                if selected == "User":
                    st.markdown("<p style='text-align: left; font-size: 17px;'>Select a movie and a user.</p>", unsafe_allow_html=True)
                    st.markdown("<p style='text-align: left; font-size: 17px;'>The 'RATED' relation will be created between User and Movie.</p>", unsafe_allow_html=True)

                    col1, col2, col3 = st.columns(3)

                    with col1:
                        user_name = st.text_input("Enter the user's name for relationship")

                    with col2:
                        movie_title = st.text_input("Enter the movie title for relationship")

                    with col3:
                        score = st.number_input("Enter the score", min_value=0.0, max_value=10.0, value=5.0, step=0.1)

                    if st.button("Create Relationship"):
                        if not user_name or not movie_title:
                            st.warning("Please enter both username and movie title.")
                        else:
                            with get_driver() as driver:
                                with driver.session() as session:
                                    session.execute_write(rate_movie, user_name.strip(), movie_title.strip(), score)
                            st.success(f"User '{user_name}' rated '{movie_title}' with {score}/10.")



                elif selected == "Movie Person":
                    st.markdown("<p style='text-align: left; font-size: 17px;'>Select a movie and a person.</p>", unsafe_allow_html=True)
                    st.markdown("<p style='text-align: left; font-size: 17px;'>The relation will be created between Person and Movie.</p>", unsafe_allow_html=True)

                    col1, col2, col3 = st.columns(3)

                    with col1:
                        person_name = st.text_input("Enter the person's name for relationship")

                    with col2:
                        movie_title = st.text_input("Enter the movie title for relationship")

                    with col3:
                        selected_roles = st.multiselect("Select one or more roles", ["ACTED_IN", "DIRECTED", "PRODUCED"])


                    ###### GUNCELLENECEK ######
                    # Add a button to create the relationship
                    if st.button("Create Relationship"):
                        if not person_name or not movie_title or not selected_roles:
                            st.warning("Please fill in all fields.")
                        else:
                            with get_driver() as driver:
                                with driver.session() as session:
                                    session.execute_write(link_movieperson_to_movie, person_name.strip(), movie_title.strip(), selected_roles)
                            st.success(f"{person_name} linked to '{movie_title}' as: {', '.join(selected_roles)}")


        ###### GUNCELLENECEK ######
        with tab2:
            st.markdown("<h3 style='text-align: left; font-size: 20px;'>Add by Query</h3>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: left; font-size: 17px; margin-bottom: 30px;'>You can add data to the database using a Cypher query.</p>", unsafe_allow_html=True)

            query = st.text_area("Enter your Cypher query here", height=100, placeholder="E.g., CREATE (:Person {name: 'Neo', age: 30})")

            if st.button("Execute Query"):
                if not query.strip():
                    st.warning("Please enter a query.")
                else:
                    with st.spinner("Running your query..."):
                        try:
                            driver = get_driver()
                            with driver.session() as session:
                                result = session.run(query)
                                records = list(result)

                                if records:
                                    df = pd.DataFrame([r.data() for r in records])
                                    st.dataframe(df)
                                else:
                                    st.success("✅ Query executed successfully. No return values.")

                        except Exception as e:
                            st.error(f"❌ Error running query:\n\n{e}")


    if st.session_state.page == "Delete Data":
        st.markdown("<h1 style='text-align: left; font-size: 30px;'>Delete Data from DB</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 18px;'>Use the form below to delete data from your Neo4j database.</p>", unsafe_allow_html=True)

        # Add your form for deleting data here
        # For example, you can use st.text_input() to get user input for deleting a person, movie, etc.


        tab1, tab2 = st.tabs(["Delete by Selection", "Delete by Query"])

        with tab1:
            st.markdown("<p style='text-align: left; font-size: 17px;'>Select a option for deleting data to database.</p>", unsafe_allow_html=True)

            option = st.selectbox(
                "Select an option",
                ("Delete Person", "Delete Movie", "Delete Relationship" ,"Delete All Data"),
            )

            st.markdown("---")

            if option == "Delete Person":
                st.markdown("<h3 style='text-align: left; font-size: 20px;'>Delete Person</h3>", unsafe_allow_html=True)

                selected_category = st.selectbox("Select Category", ["User", "Movie Person"])

                if selected_category == "User":
                    st.markdown("<p style='text-align: left; font-size: 17px;'>Select a user to delete.</p>", unsafe_allow_html=True)

                    name = st.text_input("Enter the user's name to delete")

                    if st.button("Delete User"):
                        if not name:
                            st.warning("Please enter a name.")
                        else:
                            with get_driver() as driver:
                                with driver.session() as session:
                                    session.execute_write(delete_user, name.strip())
                            st.success(f"User '{name}' was deleted successfully!")

                elif selected_category == "Movie Person":
                    st.markdown("<p style='text-align: left; font-size: 17px;'>Select a movie person to delete.</p>", unsafe_allow_html=True)
                    name = st.text_input("Enter the person's name to delete")

                    if st.button("Delete Person"):
                        if not name:
                            st.warning("Please enter a name.")
                        else:
                            with get_driver() as driver:
                                with driver.session() as session:
                                    session.execute_write(delete_person, name.strip())
                            st.success(f"Movie Person '{name}' was deleted successfully!")


            elif option == "Delete Movie":
                st.markdown("<h3 style='text-align: left; font-size: 20px;'>Delete Movie</h3>", unsafe_allow_html=True)

                title = st.text_input("Enter the movie title to delete")

                if st.button("Delete Movie"):
                    if not title:
                        st.warning("Please enter a movie title.")
                    else:
                        with get_driver() as driver:
                            with driver.session() as session:
                                session.execute_write(delete_movie, title=title.strip())
                        st.success(f"Movie '{title}' deleted successfully!")


            elif option == "Delete Relationship":
                st.markdown("<h3 style='text-align: left; font-size: 20px;'>Delete Relationship</h3>", unsafe_allow_html=True)
                st.markdown("<p style='text-align: left; font-size: 17px;'>Select a relationship type to delete.</p>", unsafe_allow_html=True)
                source_label = st.selectbox("Source Type", ["Person", "User"])

                if source_label == "Person":

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        source_name = st.text_input("Source Name")
                    with col2:
                        target_title = st.text_input("Target Movie Title")
                    with col3:
                        rel_type = st.selectbox("Relationship Type", ["ACTED_IN", "DIRECTED", "PRODUCED"])

                    submitted = st.button("Delete Relationship")

                    if submitted:
                        driver = get_driver()

                        with driver.session() as session:
                            result = session.execute_write(
                                delete_person_relationship, source_name, target_title, rel_type, source_label)

                        if result["status"] == "deleted":
                            if "score" in result:
                                st.info(f"Deleted score: {result['score']}")
                            st.success(f"Deleted relationship {rel_type} between '{source_name}' and '{target_title}'")
                        else:
                            st.warning("No matching relationship found or deleted.")


                elif source_label == "User":
                    col1, col2 = st.columns(2)
                    with col1:
                        source_name = st.text_input("Source User Name")
                    with col2:
                        target_title = st.text_input("Target Movie Title")


                    submitted = st.button("Delete Relationship")

                    if submitted:
                        driver = get_driver()

                        with driver.session() as session:
                            result = session.execute_write(
                                delete_user_relationship, source_name, target_title)

                        if result["status"] == "deleted":
                            if "score" in result:
                                st.info(f"Deleted score: {result['score']}")
                            st.success(f"Deleted relationship RATED between '{source_name}' and '{target_title}'")
                        else:
                            st.warning("No matching relationship found or deleted.")



            elif option == "Delete All Data":
                st.markdown("<h3 style='text-align: left; font-size: 20px;'>Delete All Data</h3>", unsafe_allow_html=True)
                st.markdown("<p style='text-align: left; font-size: 17px;'>This will delete all nodes and relationships in the database.</p>", unsafe_allow_html=True)

                if st.button("Delete All Data"):
                    with get_driver() as driver:
                        with driver.session() as session:
                            session.execute_write(delete_all)
                    st.success("All data deleted successfully!")

        with tab2:
            st.markdown("<h3 style='text-align: left; font-size: 20px;'>Delete by Query</h3>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: left; font-size: 17px; margin-bottom: 30px'>You can delete data from the database using a Cypher query.</p>", unsafe_allow_html=True)

            query = st.text_area("Enter your Cypher query here", height=100, placeholder="E.g., MATCH (n) DETACH DELETE n")

            if st.button("Execute Query"):
                if not query.strip():
                    st.warning("Please enter a query.")
                else:
                    with st.spinner("Running your query..."):
                        try:
                            driver = get_driver()
                            with driver.session() as session:
                                result = session.run(query)
                                records = list(result)

                                if records:
                                    df = pd.DataFrame([r.data() for r in records])
                                    st.dataframe(df)
                                else:
                                    st.success("✅ Query executed successfully. No return values.")

                        except Exception as e:
                            st.error(f"❌ Error running query:\n\n{e}")


    if st.session_state.page == "Explore / Visualize":
        st.title("🔎 Explore and Visualize the Neo4j Graph")
        st.subheader("Database Overview")
        show_statistics()

        st.subheader("Graph View")
        selected_types = st.multiselect("Filter by Node Types", ["Person", "Movie", "Genre", "User"])
        with st.spinner("Loading interactive graph..."):
            graph_data = get_graph_data(selected_types)
            net = draw_network(graph_data, selected_types)
            net.save_graph("graph.html")

            with open("graph.html", "r", encoding="utf-8") as f:
                html = f.read()
            components.html(html, height=600, scrolling=True)

        st.subheader("Search Nodes")
        term = st.text_input("Search by name/title")
        if term:
            results = search_node(term)
            st.write(results)

        st.subheader("🔗 Top Connected Nodes")
        df_rel = show_relationship_counts()
        st.dataframe(df_rel)
        st.bar_chart(df_rel.set_index("node"))

        st.subheader("⬇️ Export Data")
        st.markdown("<p style='text-align: left; font-size: 15px;'>You can export the top connected nodes or the full graph data.</p>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 15px;'>Select the type of export you want to perform.</p>", unsafe_allow_html=True)
        export_option = st.selectbox("Select export type:", ["Top Connected Nodes", "Full Graph Data"])

        if export_option == "Top Connected Nodes":
            st.download_button("Export Top Relations CSV", data=df_rel.to_csv(index=False).encode("utf-8"), file_name="top_relations.csv")

        elif export_option == "Full Graph Data":
            driver = get_driver()
            with driver.session() as session:
                result = session.run("MATCH (n)-[r]->(m) RETURN n, type(r) AS rel_type, m")
                records = result.data()
                full_df = pd.DataFrame([{
                "source": rec["n"].get("name") or rec["n"].get("title") or "Unnamed Source",
                "target": rec["m"].get("name") or rec["m"].get("title") or "Unnamed Target",
                "relationship": rec["rel_type"]
            } for rec in records])

            st.download_button("Export Full Graph CSV", data=full_df.to_csv(index=False).encode("utf-8"), file_name="full_graph_data.csv")


    if st.session_state.page == "ML & Analysis":
        st.markdown("<h1 style='text-align: left; font-size: 30px;'>Machine Learning & Analysis</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 18px;'>Use the options below to perform machine learning analysis on your Neo4j database.</p>", unsafe_allow_html=True)

        # Add your options for machine learning analysis here
        # For example, you can use st.selectbox() to let users choose what kind of analysis to perform

        tabs = st.tabs(["🎯 Degree Distribution", "🧩 Community Detection", "⭐ Centralities", "📊 Knowledge Graph Completion", "📈 Link Prediction", "Similarity Graph"])


        with tabs[0]:
            st.markdown("<h3 style='text-align: left; font-size: 20px;'>Degree Distribution</h3>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: left; font-size: 18px;'>This graph shows the degree distribution of the nodes in the database.</p>", unsafe_allow_html=True)

            degrees = get_degree_distribution()

            if degrees:
                fig = px.histogram(
                    x=degrees,
                    nbins=30,
                    labels={'x': 'Degree', 'y': 'Node Count'},
                    title="Node Degree Distribution",
                )
                fig.update_traces(marker_color='indianred')
                fig.update_layout(
                    xaxis_title="Degree",
                    yaxis_title="Number of Nodes",
                    bargap=0.1
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Veri bulunamadı. Lütfen Neo4j veritabanını kontrol edin.")

            st.markdown("""
                **📘 Note:** This graph shows how many connections each node has. A higher degree indicates that the node is highly connected and may be more centrally located in the network.
                """)


        with tabs[1]:
            st.markdown("<h3 style='text-align: left; font-size: 20px;'>Community Detection with Louvain Algorithm</h3>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: left; font-size: 18px;'>This section allows you to detect communities in the graph using the Louvain algorithm.</p>", unsafe_allow_html=True)

            if st.button("Run Louvain Algorithm"):

                with st.spinner("Algorithm is running..."):
                    result = run_louvain_community_detection(driver, graph_name='full-movie-graph')

                    if result:
                        st.success("Louvain algorithm ran successfully!")

                        st.write(f"🔹 Total number of communities: {result.get('communityCount', 'N/A')}")
                        st.write(f"🔹 Modularity score: {result.get('modularity', 'N/A')}")

                        # Topluluk bazında detaylı veri çekiliyor
                        with driver.session() as session:
                            community_data = session.execute_read(get_community_data)

                        if community_data:
                            st.write("Number of nodes per community:")

                            # Burada örnek olarak Streamlit'in bar_chart fonksiyonunu kullanabiliriz:
                            import pandas as pd

                            df = pd.DataFrame(community_data)
                            community_counts = df['community'].value_counts().sort_index()
                            st.bar_chart(community_counts)

                            st.write("Detailed community assignment data")
                            st.dataframe(df)

                        else:
                            st.warning("No detailed community data available. Only summary results are shown.")
                    else:
                        st.warning("Algorithm failed to run or returned no results.")
            else:
                st.info("Click the button to run the Louvain algorithm.")



        with tabs[2]:
            st.markdown("<h3 style='text-align: left; font-size: 20px;'>Centralities</h3>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: left; font-size: 18px;'>This section allows you to analyze the centrality of nodes in the graph.</p>", unsafe_allow_html=True)
            clearGDS()  
            create_gds_projection()


            centrality_options = [
            "Degree Centrality",
            "Betweenness Centrality",
            "PageRank"
            ]

            selected_centrality = st.selectbox("Select Centrality Measure", centrality_options)

            if st.button("Run Centrality"):

                with st.spinner("Clearing previous GDS data..."):
                    clearGDS()

                with st.spinner("Creating GDS projection..."):
                    create_gds_projection()

                with st.spinner("Running centrality algorithm..."):
                    if selected_centrality == "Degree Centrality":
                        centralities = degreeCentralityGDS()
                        label_y = "Degree Centrality"

                    elif selected_centrality == "Betweenness Centrality":
                        centralities = betweennessGDS()
                        label_y = "Betweenness Centrality"

                    elif selected_centrality == "PageRank":
                        centralities = pageRankGDS()
                        label_y = "PageRank Centrality"

                    if centralities:
                        with st.spinner("Fetching centrality results..."):
                            st.subheader(f"Top 10 Centrality Nodes - {selected_centrality}")
                            st.table(centralities)

                            names = [row['name'] for row in centralities]
                            scores = [row['score'] for row in centralities]

                            fig = px.bar(x=names, y=scores, labels={'x': 'Node', 'y': label_y})
                            st.plotly_chart(fig)
                    else:
                        st.warning("Centrality result not found.")



        with tabs[3]:
            st.markdown("<h3 style='text-align: left; font-size: 20px;'>Knowledge Graph Completion</h3>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: left; font-size: 18px;'>This section allows you to analyze the distribution of nodes and relationships in the knowledge graph.</p>", unsafe_allow_html=True)
            
            options = ["Node Distribution by Label", "Relationship Distribution"]
            selected_option = st.selectbox("Select an option", options)

            if st.button("Show Knowledge Graph Distribution"):
                
                if selected_option == "Node Distribution by Label":
                    with st.spinner("Fetching node distribution..."):
                        node_dist = get_node_label_distribution()
                    
                        st.subheader("Node Label Distribution")
                        st.table(node_dist)

                        labels = [row['label'] for row in node_dist]
                        counts = [row['count'] for row in node_dist]

                        fig = px.pie(names=labels, values=counts, title="Node Types Distribution")
                        st.plotly_chart(fig)

                elif selected_option == "Relationship Distribution":
                    with st.spinner("Fetching relationship distribution..."):
                        rel_dist = get_relationship_distribution()

                        st.subheader("Relationship Type Distribution")
                        st.table(rel_dist)

                        rel_labels = [row['relationship_type'] for row in rel_dist]
                        rel_counts = [row['count'] for row in rel_dist]

                        fig2 = px.bar(x=rel_labels, y=rel_counts, labels={'x': 'Relationship Type', 'y': 'Count'}, title="Relationship Types Frequency")
                        st.plotly_chart(fig2)


        with tabs[4]:
            st.markdown("<h3 style='text-align: left; font-size: 20px;'>Link Prediction</h3>", unsafe_allow_html=True)

            # Modelleri ve encoder’ları yükle / eğit
            models, user_enc, movie_enc = load_model()
            df = getAllData()

            # Kullanıcı seçimi
            selected_user = st.selectbox("Select a user for prediction:", user_enc.classes_)

            if st.button("Create Prediction") and selected_user:
                with st.spinner("Creating predictions…"):
                    # Her model için öneri tablosu
                    for name, mdl in models.items():
                        recs = recommend_movies(selected_user, mdl, df, user_enc, movie_enc)
                        st.subheader(f"Top Recommendations by {name}")
                        st.table(recs)

                    # Metriğe Göre Karşılaştırma Tablosu
                    st.markdown("### Models Comparison by Metrics")
                    results_df = pd.read_json("results_df.json", orient="records", lines=True)
                    st.dataframe(results_df)

                    # Metriğe Göre Karşılaştırma Grafikleri
                    # —————————————————————————————
                    # Model’i index’e alıp sadece metrik sütunlarına odaklanıyoruz
                    metrics_df = (
                        results_df
                        .set_index('Model')[['MSE','MAE','R2']]
                        .rename_axis(index='Model')
                    )

                    st.markdown("### Metrics Bar Chart")
                    # Streamlit’in hızlı çubuk grafik fonksiyonu
                    st.bar_chart(metrics_df)

                    # Eğer ayrı ayrı grafikleri tercih ederseniz:
                    cols = st.columns(3)
                    with cols[0]:
                        st.markdown("**MSE by Model**")
                        st.bar_chart(metrics_df[['MSE']])
                    with cols[1]:
                        st.markdown("**MAE by Model**")
                        st.bar_chart(metrics_df[['MAE']])
                    with cols[2]:
                        st.markdown("**R2 by Model**")
                        st.bar_chart(metrics_df[['R2']])
            else:
                st.warning("Lütfen önce bir kullanıcı seçip ‘Create Prediction’ butonuna tıklayın.")

        with tabs[5]:
            st.markdown("<h3 style='text-align: left; font-size: 20px;'>Similarity Graph</h3>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: left; font-size: 18px;'>This section allows you to visualize the similarity graph of movies.</p>", unsafe_allow_html=True)

            if st.button("Find Similar Movies"):
                df= get_similarity_graph()

                st.write("Top 20 Similar Movies:")
                st.table(df)
                
                # Create a network graph
                net = Network(
                    height="600px", width="100%", 
                    bgcolor="#ffffff", font_color="black", directed=True
                )

                # 3) Düğümleri ekle
                for node in pd.concat([df['movie1'], df['movie2']]).unique():
                    net.add_node(node, label=node, title=node)

                # 4) Kenarları ekle (kalınlık similarity’ye orantılı)
                for _, row in df.iterrows():
                    net.add_edge(
                        row['movie1'], row['movie2'], 
                        value=row['sim'], 
                        title=f"sim: {row['sim']}"
                    )

                # 5) Fiziksel simülasyon ve ayarlar
                net.toggle_physics(True)
                net.repulsion(node_distance=150, central_gravity=0.2)

                # 6) HTML olarak render et ve Streamlit’e göm
                html = net.generate_html()
                components.html(html, height=650, scrolling=True)

    if st.session_state.page == "About & Settings":
        st.markdown("<h1 style='text-align: left; font-size: 30px;'>About & Settings</h1>", unsafe_allow_html=True)


        st.markdown("<h3 style='text-align: left; font-size: 20px;'>About</h3>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 16px;'>This app is built using Streamlit and Neo4j.</p>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 16px;'>It allows you to add, delete, and visualize data in your Neo4j database.</p>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: left; font-size: 16px;'>You can also explore the data and see the relationships between different entities.</p>", unsafe_allow_html=True)
        # Add your settings and information here
        # For example, you can use st.text_input() to let users change settings or view information about the app
        st.markdown("---")
        st.markdown("<h3 style='text-align: left; font-size: 20px;'>Settings</h3>", unsafe_allow_html=True)


else:
    st.markdown("<h1 style='text-align: left; font-size: 30px;'>Neo4j Connection Error</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: left; font-size: 18px;'>Please check your Neo4j connection settings.</p>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: left; font-size: 18px;'>Make sure the Neo4j server is running and the credentials are correct.</p>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: left; font-size: 18px;'>You can also check the Neo4j logs for more information.</p>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: left; font-size: 18px;'>Click the button below to reload the page and check the connection again.</p>", unsafe_allow_html=True)

    if st.button("🔄 Refresh"):
        with st.spinner("Refreshing..."):
            st.rerun()
