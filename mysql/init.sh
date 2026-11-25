#!/bin/bash
set -eu
# Restrict generated account values to avoid SQL injection during initialization.
case "$MYSQL_USERNAME" in *[!a-zA-Z0-9_]*) echo 'Invalid reader username'; exit 1;; esac
case "$MYSQL_PASSWORD" in *[!a-zA-Z0-9_-]*) echo 'Use letters, numbers, underscore or dash in MYSQL_PASSWORD'; exit 1;; esac
mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" <<SQL
CREATE TABLE production (id INT PRIMARY KEY AUTO_INCREMENT, production_date DATE NOT NULL, product_code VARCHAR(50) NOT NULL, input_qty INT NOT NULL, good_output INT NOT NULL, ng INT NOT NULL);
CREATE USER '${MYSQL_USERNAME}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';
GRANT SELECT ON production_db.production TO '${MYSQL_USERNAME}'@'%';
SQL
for day in $(seq 1 20); do
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -e "INSERT INTO production (production_date,product_code,input_qty,good_output,ng) VALUES ('2026-11-$day','PCB-A',1000,$((950+day)),$((50-day)));"
done
