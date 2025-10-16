workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:8000"
accesslog = "/var/www/backend/ads_extractor_be/backend/logs/gunicorn_access.log"
errorlog = "/var/www/backend/ads_extractor_be/backend/logs/gunicorn_error.log"
loglevel = "info"