from sqlglot import exp
from sqlglot.dialects.dialect import Dialect, inline_array_sql, var_map_sql
from sqlglot.generator import Generator
from sqlglot.parser import Parser, parse_var_map
from sqlglot.tokens import Tokenizer, TokenType


class ClickHouse(Dialect):
    normalize_functions = None
    null_ordering = "nulls_are_last"

    class Tokenizer(Tokenizer):
        IDENTIFIERS = ['"', "`"]

        KEYWORDS = {
            **Tokenizer.KEYWORDS,
            "NULLABLE": TokenType.NULLABLE,
            "FINAL": TokenType.FINAL,
            "DATETIME64": TokenType.DATETIME,
            "INT8": TokenType.TINYINT,
            "INT16": TokenType.SMALLINT,
            "INT32": TokenType.INT,
            "INT64": TokenType.BIGINT,
            "FLOAT32": TokenType.FLOAT,
            "FLOAT64": TokenType.DOUBLE,
        }

    class Parser(Parser):
        FUNCTIONS = {
            **Parser.FUNCTIONS,
            "MAP": parse_var_map,
        }

        def _parse_table(self, schema=False):
            this = super()._parse_table(schema)

            if self._match(TokenType.FINAL):
                this = self.expression(exp.Final, this=this)

            return this

    class Generator(Generator):
        STRUCT_DELIMITER = ("(", ")")

        TYPE_MAPPING = {
            **Generator.TYPE_MAPPING,
            exp.DataType.Type.NULLABLE: "Nullable",
            exp.DataType.Type.DATETIME: "DateTime64",
        }

        TRANSFORMS = {
            **Generator.TRANSFORMS,
            exp.Array: inline_array_sql,
            exp.Final: lambda self, e: f"{self.sql(e, 'this')} FINAL",
            exp.Map: var_map_sql,
            exp.VarMap: var_map_sql,
        }

        EXPLICIT_UNION = True
