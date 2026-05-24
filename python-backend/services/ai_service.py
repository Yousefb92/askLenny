import json
import re
from clients.llm_client import generate_text

class AIDescriptionService:
    @staticmethod
    def generate_description(db_name: str, table_name: str, column_name: str = None, data_type: str = None,
                             table_columns: list[str] = None) -> str:

        # 1. Column-Level Context
        if column_name:
            prompt = (
                f"You are a database architect. Write a single, concise sentence explaining "
                f"the purpose of a column named '{column_name}' (type: {data_type}) "
                f"which lives inside the '{table_name}' table of the '{db_name}' database. "
                f"Return ONLY the sentence, no conversational filler or markdown formatting."
            )

        # 2. Table-Level Context
        else:
            col_context = ""
            if table_columns:
                col_string = ", ".join(table_columns)
                col_context = f" The table contains the following columns: [{col_string}]. Use these to infer the table's true purpose."

            prompt = (
                f"You are a database architect. Write a single, concise sentence explaining "
                f"the likely purpose of a database table named '{table_name}' "
                f"inside the '{db_name}' database.{col_context} "
                f"Return ONLY the sentence, no conversational filler or markdown formatting."
            )

        print(f"Calling Gemini AI for: {table_name} -> {column_name or 'Table Level'}")

        # Call the client to get the actual text
        return generate_text(prompt)

    @staticmethod
    def generate_batch_column_descriptions(
        db_name: str,
        table_name: str,
        table_description: str,
        columns: list[dict],   # [{"name": "ColName", "data_type": "int"}, ...]
    ) -> dict[str, str]:
        """
        Generates descriptions for multiple columns in a single LLM call.
        Returns {column_name: description} for every column in the list.
        The caller is responsible for filtering out columns that already
        have descriptions (so existing work is never overwritten).
        """
        if not columns:
            return {}

        col_lines = "\n".join(
            f"- {col['name']} ({col.get('data_type') or 'unknown type'})"
            for col in columns
        )

        context_line = (
            f"The table's purpose: {table_description}\n\n"
            if table_description else ""
        )

        prompt = (
            f"You are a database architect. The following columns belong to the "
            f"'{table_name}' table in the '{db_name}' database.\n"
            f"{context_line}"
            f"Write a single concise sentence for each column explaining its purpose.\n"
            f"Return ONLY a valid JSON object — column names as keys, descriptions as "
            f"string values. No markdown code fences, no explanation outside the JSON.\n\n"
            f"Columns:\n{col_lines}"
        )

        print(f"Calling Gemini AI for batch enrichment: {table_name} ({len(columns)} columns)")
        raw = generate_text(prompt)

        # Strip markdown code fences in case the model adds them anyway
        clean = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.IGNORECASE)
        clean = re.sub(r'\s*```$', '', clean.strip())

        try:
            result = json.loads(clean)
            return {k: str(v) for k, v in result.items() if v}
        except json.JSONDecodeError as e:
            print(f"Batch enrichment JSON parse error: {e}\nRaw:\n{raw[:400]}")
            raise ValueError(f"LLM returned an unparseable response. Try again.")