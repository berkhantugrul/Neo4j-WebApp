from neo4j import GraphDatabase
import pandas as pd
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.neighbors import KNeighborsRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error 
import joblib
import numpy as np

uri = "bolt://localhost:7687"
username = "neo4j"
password = "password"

driver = GraphDatabase.driver(uri, auth=(username, password))


# Kişi ekle
def add_movie_person(tx, name, age, gender, roles):
    tx.run("""
        MERGE (p:Person {name: $name})
        SET p.age = $age,
            p.gender = $gender,
            p.roles = $roles
    """, name=name, age=age, gender=gender, roles=roles)

# Add user
def add_user(tx, username):
    tx.run("""
        MERGE (u:User {username: $username})
    """, username=username)

# Film ekle
def add_movie_with_genres(tx, title, year, genres):
    tx.run("""
        MERGE (m:Movie {title: $title})
        SET m.year = $year,
            m.genres = $genres
    """, title=title, year=year, genres=genres)
    

    for genre in genres:
        tx.run("""
            MERGE (g:Genre {name: $genre})
            WITH g
            MATCH (m:Movie {title: $title})
            MERGE (m)-[:IN_GENRE]->(g)
        """, title=title, genre=genre)


# Oyunculuğu bağla
def link_movieperson_to_movie(tx, person_name, movie_title, roles):
    for role in roles:
        tx.run(f"""
            MATCH (p:Person {{name: $person_name}})
            MATCH (m:Movie {{title: $movie_title}})
            MERGE (p)-[r:{role}]->(m)
        """, person_name=person_name, movie_title=movie_title)

# User - Rate Movie ilişkisini oluştur
def rate_movie(tx, username, movie_title, score):
    tx.run("""
        MERGE (u:User {username: $username})
        MERGE (m:Movie {title: $movie_title})
        MERGE (u)-[r:RATED]->(m)
        SET r.score = $score
    """, username=username, movie_title=movie_title, score=score)


# --- Delete helpers ---
def delete_person(tx, name):
    tx.run("MATCH (p:Person {name: $name}) DETACH DELETE p", name=name)

def delete_user(tx, username):
    tx.run("MATCH (u:User {username: $username}) DETACH DELETE u", username=username)

def delete_movie(tx, title):
    tx.run("MATCH (m:Movie {title: $title}) DETACH DELETE m", title=title)

def delete_all(tx):
    tx.run("MATCH (n) DETACH DELETE n")

def delete_user_relationship(tx, source_name, target_title):
    result = tx.run(
        """
        MATCH (u:User {username: $source_name})-[r:RATED]->(m:Movie {title: $target_title})
        WITH r, r.score AS score
        DELETE r
        RETURN count(r) AS deleted_count, score
        """,
        source_name=source_name,
        target_title=target_title
    ).single()

    if result and result["deleted_count"] > 0:
        return {"status": "deleted", "score": result["score"]}
    else:
        return {"status": "not_found", "score": None}



def delete_person_relationship(tx, source_name, target_title, rel_type):
    result = tx.run(
        """
        MATCH (p:Person {name: $source_name})-[r]->(m:Movie {title: $target_title})
        WHERE type(r) = $rel_type
        DELETE r
        RETURN count(r) AS deleted_count
        """,
        source_name=source_name,
        target_title=target_title,
        rel_type=rel_type
    ).single()

    if result and result["deleted_count"] > 0:
        return {"status": "deleted"}
    else:
        return {"status": "not_found"}


def find_most_acted(tx):
    result = tx.run(
        """
        MATCH (p:Person)-[:ACTED_IN]->(m:Movie)
        RETURN p.name AS Actor, COUNT(m) AS MovieCount
        ORDER BY MovieCount DESC
        LIMIT 10
        """,
    ).single()

    if result:
        return {"name": result["person_name"], "acted_count": result["acted_count"]}
    else:
        return None


def genre_movie_count(tx):
    result = tx.run(
        """
        MATCH (m:Movie)-[:IN_GENRE]->(g:Genre)
        RETURN g.name AS Genre, COUNT(m) AS Count
        ORDER BY Count DESC
        """,
    ).single()

    if result:
        return {"name": result["genre_name"], "movie_count": result["movie_count"]}
    else:
        return None

def highest_ratings(tx):
    result = tx.run(
        """
        MATCH (u:User)-[r:RATED]->(m:Movie)
        RETURN m.title AS Movie, avg(r.score) AS AvgRating, count(*) AS RatingCount
        ORDER BY AvgRating DESC
        LIMIT 10
        """,
    ).single()

    if result:
        return {"title": result["movie_title"], "avg_rating": result["avg_rating"]}
    else:
        return None

def most_related_movies(tx):
    result = tx.run(
        """
        MATCH (m:Movie)<-[r]-(p:Person)
        RETURN m.title AS Movie, COUNT(r) AS TotalLinks
        ORDER BY TotalLinks DESC
        LIMIT 10

        """,
    ).single()

    if result:
        return {"title": result["movie_title"], "rating_count": result["rating_count"]}
    else:
        return None
    

def acted_together(tx):
    result = tx.run(
        """
        MATCH (p1:Person)-[:ACTED_IN]->(m:Movie)<-[:ACTED_IN]-(p2:Person)
        WHERE p1 <> p2
        RETURN p1.name AS Actor1, p2.name AS Actor2, COUNT(m) AS SharedMovies
        ORDER BY SharedMovies DESC
        LIMIT 10
        """,
    ).single()

    if result:
        return {"actor1": result["actor1_name"], "actor2": result["actor2_name"], "shared_movies": result["shared_movies_count"]}
    else:
        return None   


def get_degree_distribution():
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))

    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            RETURN COUNT { (n)--() } AS degree
            ORDER BY degree DESC
            LIMIT 10
        """)
        return [record["degree"] for record in result]



def run_louvain_community_detection(driver, graph_name):
    query = f"""
    CALL gds.louvain.write('{graph_name}', {{
        writeProperty: 'community'
    }})
    YIELD communityCount, modularity, modularities
    """
    def run_tx(tx):
        result = tx.run(query)
        return result.single().data()

    with driver.session() as session:
        return session.execute_write(run_tx)

def get_community_data(tx):
    query = """
    MATCH (n)
    WHERE n.community IS NOT NULL
    RETURN 
    coalesce(n.name, n.title) AS node, 
    n.community AS community
    ORDER BY community
    """
    result = tx.run(query)
    return [record.data() for record in result]


def co_acting_network(tx):
    result = tx.run(
        """
        CALL gds.graph.project.cypher(
        'coacting-graph',
        'MATCH (p:Person) RETURN id(p) AS id',
        '''
        MATCH (p1:Person)-[:ACTED_IN]->(m:Movie)<-[:ACTED_IN]-(p2:Person)
        WHERE id(p1) < id(p2)
        RETURN id(p1) AS source, id(p2) AS target, count(*) AS weight
        '''
        )
        """,
    ).single()

    if result:
        return {"actor1": result["actor1_name"], "actor2": result["actor2_name"], "shared_movies": result["shared_movies_count"]}
    else:
        return None


def node_similarity(tx):
    result = tx.run(
        """
        CALL gds.nodeSimilarity.stream('coacting-graph')
        YIELD node1, node2, similarity
        RETURN gds.util.asNode(node1).name AS Person1,
            gds.util.asNode(node2).name AS Person2,
            similarity
        ORDER BY similarity DESC
        LIMIT 10
        """,
    ).single()

    if result:
        return {"name1": result["name1"], "name2": result["name2"], "similarity": result["similarity"]}
    else:
        return None
    

def get_communities(driver):
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            WHERE n.community IS NOT NULL
            RETURN n.community AS community, count(*) AS size
            ORDER BY size DESC
        """)
        return [(record["community"], record["size"]) for record in result]



#### LINK PREDICTION ####

def getAllData():
    query = """
    MATCH (u:User)-[r:RATED]->(m:Movie)
    RETURN 
        COALESCE(u.name, u.title) AS user, 
        COALESCE(m.title, m.name) AS movie, 
        r.rating AS rating
    """

    with driver.session() as session:
        results = session.run(query)
        records = [dict(record) for record in results]

    df = pd.DataFrame(records)
    return df

MODEL_FILES = {
    "RandomForest": "RandomForest.pkl",
    "Ridge":        "Ridge.pkl",
    "KNN":          "KNN.pkl",
}
USER_ENC_FILE  = "user_encoder.pkl"
MOVIE_ENC_FILE = "movie_encoder.pkl"

def encodeTrainTest(df):
    # 1) Encoder'ları oluştur
    user_enc = LabelEncoder()
    movie_enc = LabelEncoder()
    df['user_id']  = user_enc.fit_transform(df['user'])
    df['movie_id'] = movie_enc.fit_transform(df['movie'])

    # 2) Eğitim / test ayır
    X = df[['user_id', 'movie_id']]
    y = df['rating']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # 3) Modelleri tanımla
    models = {
        "RandomForest": RandomForestRegressor(n_estimators=100, random_state=42),
        "Ridge":        Ridge(alpha=1.0),
        "KNN":          KNeighborsRegressor(n_neighbors=5),
    }

    results = []
    comparison_dfs = {}

    # 4) Modelleri eğit, skorları hesapla, kayıt et
    for name, mdl in models.items():
        mdl.fit(X_train, y_train)
        preds = mdl.predict(X_test)

        # performans metrikleri
        mse = mean_squared_error(y_test, preds)
        mae = mean_absolute_error(y_test, preds)
        r2  = r2_score(y_test, preds)

        results.append({
            'Model': name, 'MSE': mse,
            'MAE': mae, 'R2': r2
        })

        # detaylı karşılaştırma dataframe’i (isteğe bağlı)
        temp = X_test.copy()
        temp['actual']    = y_test
        temp['predicted'] = preds
        temp['user']      = user_enc.inverse_transform(temp['user_id'])
        temp['movie']     = movie_enc.inverse_transform(temp['movie_id'])
        comparison_dfs[name] = temp[['user','movie','actual','predicted']]

        # her modeli ayrı dosyaya kaydet
        joblib.dump(mdl, MODEL_FILES[name])

    # encoder çiftini de kaydet
    joblib.dump(user_enc,  USER_ENC_FILE)
    joblib.dump(movie_enc, MOVIE_ENC_FILE)

    # sonuçları JSON'a yaz
    results_df = pd.DataFrame(results)
    results_df.to_json("results_df.json", orient="records", lines=True)

    return models, user_enc, movie_enc

def recommend_movies(user_name, model, df, user_enc, movie_enc, top_n=10):
    # Eğer henüz encode edilmemişse, hemen sütunları ekleyelim
    if 'user_id' not in df.columns or 'movie_id' not in df.columns:
        df = df.copy()
        df['user_id']  = user_enc.transform(df['user'])
        df['movie_id'] = movie_enc.transform(df['movie'])

    user_id = user_enc.transform([user_name])[0]
    rated   = df[df['user_id'] == user_id]['movie_id'].unique()
    all_movies = df['movie_id'].unique()
    unrated = [m for m in all_movies if m not in rated]

    candidate_df = pd.DataFrame({
        'user_id': [user_id] * len(unrated),
        'movie_id': unrated
    })
    candidate_df['predicted_rating'] = model.predict(candidate_df)

    top_recs = (
        candidate_df
        .sort_values('predicted_rating', ascending=False)
        .head(top_n)
    )
    top_recs['movie'] = movie_enc.inverse_transform(top_recs['movie_id'])

    return top_recs[['movie', 'predicted_rating']].round(2)




########## GDS GRAPH CREATION ##########

def clearGDS():
    query = """
        CALL gds.graph.drop('full-movie-graph', false)
        YIELD graphName
        """
    
    def run_tx(tx):
        result = tx.run(query)
        return result.single()
    
    with driver.session() as session:
        return session.execute_write(run_tx)

def create_gds_projection():
    query = """
        CALL gds.graph.project(
            'full-movie-graph',
            ['Person', 'Movie', 'Genre', 'User'],
            {
                ACTED_IN:   {orientation: 'UNDIRECTED'},
                DIRECTED:   {orientation: 'UNDIRECTED'},
                IN_GENRE:   {orientation: 'UNDIRECTED'},
                RATED:      {orientation: 'UNDIRECTED'}
            }
            )
        """
    
    def run_tx(tx):
        result = tx.run(query)
        return result.single()
    
    with driver.session() as session:
        return session.execute_write(run_tx)

def pageRankGDS():
    query = f"""
        CALL gds.pageRank.stream('full-movie-graph')
            YIELD nodeId, score
            RETURN 
            gds.util.asNode(nodeId).name AS name,
            labels(gds.util.asNode(nodeId)) AS labels,
            ROUND(score, 4) AS score
            ORDER BY score DESC
            LIMIT 10
        """
    def run_tx(tx):
        result = tx.run(query)
        return [record.data() for record in result]
    
    with driver.session() as session:
        return session.execute_write(run_tx)

def betweennessGDS():
    query = f"""
        CALL gds.betweenness.stream('full-movie-graph')
            YIELD nodeId, score
            RETURN 
            gds.util.asNode(nodeId).name AS name,
            labels(gds.util.asNode(nodeId)) AS labels,
            ROUND(score, 2) AS score
            ORDER BY score DESC
            LIMIT 10
        """
    
    def run_tx(tx):
        result = tx.run(query)
        return [record.data() for record in result]
    
    with driver.session() as session:
        return session.execute_write(run_tx)


def degreeCentralityGDS():
    query = f"""
    CALL gds.degree.stream('full-movie-graph')
            YIELD nodeId, score
            RETURN 
            gds.util.asNode(nodeId).name AS name,
            labels(gds.util.asNode(nodeId)) AS labels,
            score
            ORDER BY score DESC
            LIMIT 10
    """

    def run_tx(tx):
        result = tx.run(query)
        return [record.data() for record in result]

    with driver.session() as session:
        return session.execute_write(run_tx)
    

#################### KONWLEDGE GRAPH DISTRUBITION ####################

def get_node_label_distribution():
    query = """
    MATCH (n)
    RETURN labels(n)[0] AS label, count(*) AS count
    ORDER BY count DESC
    """
    def run_tx(tx):
        result = tx.run(query)
        return [record.data() for record in result]

    with driver.session() as session:
        return session.execute_read(run_tx)


def get_relationship_distribution():
    query = """
    MATCH ()-[r]->()
    RETURN type(r) AS relationship_type, count(*) AS count
    ORDER BY count DESC
    """
    def run_tx(tx):
        result = tx.run(query)
        return [record.data() for record in result]

    with driver.session() as session:
        return session.execute_read(run_tx)

 
def get_similarity_graph():
    query = f"""
    CALL gds.nodeSimilarity.stream('full-movie-graph')
    YIELD node1, node2, similarity
    RETURN 
    gds.util.asNode(node1).title AS movie1,
    gds.util.asNode(node2).title AS movie2,
    ROUND(similarity, 3) AS sim
    ORDER BY sim DESC
    LIMIT 20
    """
    with driver.session() as session:
        records = session.run(query)
        df = pd.DataFrame([r.data() for r in records])
    driver.close()
    return df

if __name__ == "__main__":
    df = getAllData()
    encodeTrainTest(df)