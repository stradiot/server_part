#!/bin/bash

a=$(date)
while true
do
echo $a
curl -X POST -d '{"activity": false, "heartrate": 79}' -H "Content-Type: application/json" "localhost:5000/value_update"
sleep 1
done
