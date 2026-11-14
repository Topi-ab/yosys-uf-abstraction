#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/tc.sh" sby "$@"
