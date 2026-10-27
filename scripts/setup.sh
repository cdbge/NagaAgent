#!/bin/bash
# 本脚本位于 <repo>/scripts/，setup.py 就在同一目录
cd "$(dirname "${BASH_SOURCE[0]}")"
python setup.py
