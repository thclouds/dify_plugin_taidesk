from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from .database_config import DatabaseConfig

POSTGRES_INDEXES_NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}

metadata = MetaData(naming_convention=POSTGRES_INDEXES_NAMING_CONVENTION)

db = SQLAlchemy(metadata=metadata)


def init_db(app):
    """Initialize database with configuration from DatabaseConfig."""
    config = DatabaseConfig()
    
    # Set database configuration from DatabaseConfig
    database_uri = config.SQLALCHEMY_DATABASE_URI
    if '_plugin' in database_uri:
        database_uri = database_uri.replace('_plugin', '')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
    app.config['SQLALCHEMY_POOL_SIZE'] = config.SQLALCHEMY_POOL_SIZE
    app.config['SQLALCHEMY_MAX_OVERFLOW'] = config.SQLALCHEMY_MAX_OVERFLOW
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize SQLAlchemy with app
    db.init_app(app)