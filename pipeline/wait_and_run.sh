#!/bin/zsh
cd "$(dirname "$0")"
URL="https://amp.shazam.com/discovery/v5/en/GB/iphone/-/tag/0/0?sync=true&webv3=true&sampling=true&connected=&shazamapiversion=v3&sharehub=true&video=v0"
while true; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X POST -H 'Content-Type: application/json' -H 'User-Agent: Mozilla/5.0' -d '{"timezone":"Europe/London","signature":{"uri":"data:audio/vnd.shazam.sig;base64,AA==","samplems":1000},"timestamp":1,"context":{},"geolocation":{}}' "$URL")
  echo "$(date '+%H:%M:%S') probe $code" >> logs/probe.log
  [ "$code" != "429" ] && break
  sleep 120
done
echo "$(date '+%H:%M:%S') limit lifted, starting" >> logs/probe.log
./run_all.sh
