from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

if any((settings.db_host, settings.db_user, settings.db_password)):
    if not all((settings.db_host, settings.db_user, settings.db_password)):
        raise RuntimeError("DB_HOST, DB_USER, and DB_PASSWORD must all be set together")
    database_url = URL.create(
        "mysql+pymysql",
        username=settings.db_user,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )
else:
    database_url = settings.database_url
    # Railway exposes MySQL URLs with the generic mysql:// scheme; this project uses PyMySQL.
    if database_url.startswith("mysql://"):
        database_url = "mysql+pymysql://" + database_url[len("mysql://"):]

is_mysql = database_url.get_backend_name() == "mysql" if isinstance(database_url, URL) else database_url.startswith("mysql")
is_sqlite = database_url.get_backend_name() == "sqlite" if isinstance(database_url, URL) else database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def migrate_company_sharing():
    """Additive migration for existing demo databases; preserves stored files and keys."""
    inspector = inspect(engine)
    if "files" in inspector.get_table_names() and "organization_id" not in {
        column["name"] for column in inspector.get_columns("files")
    }:
        with engine.begin() as connection:
            if is_mysql:
                connection.execute(text("ALTER TABLE files ADD COLUMN organization_id VARCHAR(36) NULL"))
                connection.execute(text("CREATE INDEX ix_files_organization_id ON files (organization_id)"))
            else:
                connection.execute(text("ALTER TABLE files ADD COLUMN organization_id VARCHAR(36) NULL"))

    inspector = inspect(engine)
    if "users" in inspector.get_table_names() and "username" not in {
        column["name"] for column in inspector.get_columns("users")
    }:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(32) NULL"))
    inspector = inspect(engine)
    if "users" in inspector.get_table_names() and not any(
        index.get("column_names") == ["username"] and index.get("unique")
        for index in inspector.get_indexes("users")
    ):
        with engine.begin() as connection:
            connection.execute(text("CREATE UNIQUE INDEX ix_users_username ON users (username)"))

    inspector = inspect(engine)
    if "files" in inspector.get_table_names() and "wrapped_key_key_id" not in {
        column["name"] for column in inspector.get_columns("files")
    }:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE files ADD COLUMN wrapped_key_key_id VARCHAR(2048) NULL"))
