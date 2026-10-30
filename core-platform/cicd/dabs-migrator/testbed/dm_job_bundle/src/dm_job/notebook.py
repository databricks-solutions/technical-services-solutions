# Databricks notebook source
# Seed notebook for the dabs-migrator test job.
print("dm_job seed notebook running")

# COMMAND ----------

df = spark.sql("SELECT 1 AS one, 'seed' AS label")
df.show()
