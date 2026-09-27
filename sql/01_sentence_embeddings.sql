CREATE TABLE juno.restaurant.sentence_embeddings AS
SELECT sentence_id,
       ai_query('databricks-gte-large-en', text) AS embedding
FROM juno.restaurant.sentences
