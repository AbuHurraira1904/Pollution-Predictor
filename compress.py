import gzip
import shutil

SOURCE = "openaq_pakistan_slim.csv"
OUTPUT = "openaq_pakistan_slim.csv.gz"

with open(SOURCE, "rb") as source, gzip.open(OUTPUT, "wb") as output:
    shutil.copyfileobj(source, output)
