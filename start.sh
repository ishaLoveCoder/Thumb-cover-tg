#!/bin/bash
gunicorn app:app & python3 angel.py
