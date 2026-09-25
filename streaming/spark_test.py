from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .appName("EcommerceIntelligence")
    .master("local[*]")
    .getOrCreate()
)

data = [
    ("Gaming Mouse", 1499),
    ("Keyboard", 3499),
    ("Headphones", 4999),
]

df = spark.createDataFrame(data, ["product", "price"])

df.show()

spark.stop()