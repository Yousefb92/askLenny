# discovery.py
from sqlalchemy import create_engine, inspect
import os
# We must import the Type definition from your config file
from core.config import DBConnector


def get_connection_uri(connector: DBConnector):
    """
    Step 1: The 'Key Maker'
    Turns your YAML settings into a secret key (URI) the computer
    can use to log in.
    """
    password = os.getenv(connector.password_env_var, "NOT_SET")

    if connector.engine == "postgresql":
        # We point to the specific database defined in YAML
        return f"postgresql://{connector.username}:{password}@{connector.server}:{connector.port}/{connector.database}"

    elif connector.engine == "mysql":
        # The 'database' part is crucial for MySQL discovery
        return f"mysql+pymysql://{connector.username}:{password}@{connector.server}:{connector.port}/{connector.database}"

    elif connector.engine == "mssql":
        # Using the pymssql driver template
        return f"mssql+pymssql://{connector.username}:{password}@{connector.server}:{connector.port}/{connector.database}"

    elif connector.engine == "oracle":
        return f"oracle+oracledb://{connector.username}:{password}@{connector.server}:{connector.port}/?service_name={connector.database}"

    elif connector.engine == "snowflake":
        # Note: Snowflake often uses an 'account' name instead of a server IP
        return f"snowflake://{connector.username}:{password}@{connector.server}/{connector.database}"

    elif connector.engine == "sqlite":
        # SQLite just needs the file path
        return f"sqlite:///{connector.database}.db"

    raise ValueError(f"Unsupported engine type: {connector.engine}")


def discover_schema(connection_string: str):
    """
    Step 2: The 'Explorer'
    Connects to the database and 'scrapes' the metadata.
    Note: It does NOT read actual rows of data (customer names, etc.),
    it only reads the STRUCTURE (the names of the tables and columns).
    """
    # Create the connection 'engine'
    engine = create_engine(connection_string)

    # The 'inspector' is a special tool that can read DB blueprints
    inspector = inspect(engine)

    schema_map = []

    # 1. Loop through every table in the database
    for table_name in inspector.get_table_names():
        columns = []

        # 2. For each table, get a list of every column
        for col in inspector.get_columns(table_name):
            columns.append({
                "name": col['name'],
                "type": str(col['type']),
                "nullable": col['nullable'],
                "primary_key": 1 if col.get('primary_key') else 0
            })

        # 3. Build a map of how tables relate to each other (Foreign Keys)
        schema_map.append({
            "table": table_name,
            "columns": columns,
            "foreign_keys": inspector.get_foreign_keys(table_name)
        })

    return schema_map