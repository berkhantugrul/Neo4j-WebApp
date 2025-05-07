from neo4j import GraphDatabase

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


