import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import uvicorn
from backend.main import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    print(f"Starting server on port {port}...")
    uvicorn.run(app, host='0.0.0.0', port=port)
