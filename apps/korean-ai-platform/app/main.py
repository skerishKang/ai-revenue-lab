from app.env_bootstrap import load_env_file

load_env_file()

from app.factory import create_app

app = create_app()
