import sys; sys.path.insert(0, '/home/zach/.config/templedb/checkouts/templedb/src')
import uvicorn; from gui import app; uvicorn.run(app, host='127.0.0.1', port=57269, log_level='error')
