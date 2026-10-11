#!/bin/zsh
cd "$(dirname "$0")" && . .venv/bin/activate
for id in c0-hvjV2A5Y vy-k0FopsmY IC5EOU0vZjw VflpW-6ezIQ; do
  python trackid.py "https://www.youtube.com/watch?v=$id" --out ../sets > logs/$id.log 2>&1
  python build_index.py >> logs/index.log 2>&1
done
echo ALLDONE > logs/ALLDONE
