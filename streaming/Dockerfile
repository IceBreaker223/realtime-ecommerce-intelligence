FROM apache/spark:4.2.0@sha256:fc64959c04bd87b0ac686be9aaa9008b69cdb1afc695400528279c8b01f43d89
USER root
RUN pip install --no-cache-dir "psycopg[binary]==3.3.6" "typing_extensions==4.16.0"
COPY . /opt/spark-apps
USER spark
