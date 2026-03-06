"""pytest configuration for nFlasher tests."""
import sys
import os

# Ensure the package root is on the path when running tests directly
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
