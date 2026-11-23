import argparse
from wsgiref.simple_server import make_server

from .store import ProjectStore
from .web import create_app


def main():
    parser = argparse.ArgumentParser(description="本地 AI 漫剧创作工作台")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="data/studio.sqlite3")
    args = parser.parse_args()
    app = create_app(ProjectStore(args.db))
    with make_server("127.0.0.1", args.port, app) as server:
        print(f"漫剧工作台 http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
