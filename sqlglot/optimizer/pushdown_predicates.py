from sqlglot import expressions as exp
from sqlglot.optimizer.normalize import normalized
from sqlglot.optimizer.optimize_joins import join_kind
from sqlglot.optimizer.scope import traverse_scope


def pushdown_predicates(expression):
    """
    Rewrite sqlglot AST to pushdown predicates in FROMS and JOINS

    Example:
        >>> import sqlglot
        >>> sql = "SELECT * FROM (SELECT * FROM x AS x) AS y WHERE y.a = 1"
        >>> expression = sqlglot.parse_one(sql)
        >>> pushdown_predicates(expression).sql()
        'SELECT * FROM (SELECT * FROM x AS x WHERE y.a = 1) AS y WHERE TRUE'

    Args:
        expression (sqlglot.Expression): expression to optimize
    Returns:
        sqlglot.Expression: optimized expression
    """
    for scope in reversed(traverse_scope(expression)):
        where = scope.expression.args.get("where")

        if not where:
            continue

        condition = where.this.unnest()

        cnf_like = normalized(condition) or not normalized(condition, dnf=True)

        predicates = list(
            condition.flatten()
            if isinstance(condition, exp.And if cnf_like else exp.Or)
            else [condition]
        )

        if cnf_like:
            for predicate in predicates:
                for node in nodes_for_predicate(predicate, scope).values():
                    predicate.replace(exp.TRUE)

                    if isinstance(node, exp.Join):
                        on = node.args.get("on")
                        node.set("on", exp.and_(predicate, on) if on else predicate)
                        break
                    elif isinstance(node, exp.Select):
                        node.where(replace_aliases(node, predicate), copy=False)
        else:
            pushdown = set()

            for a in predicates:
                a_tables = set(exp.column_table_names(a))

                for b in predicates:
                    a_tables &= set(exp.column_table_names(b))

                pushdown.update(a_tables)

            conditions = {}

            for table in sorted(pushdown):
                for predicate in predicates:
                    nodes = nodes_for_predicate(predicate, scope)

                    if table not in nodes:
                        continue

                    predicate_condition = None

                    for column in predicate.find_all(exp.Column):
                        if column.text("table") == table:
                            condition = column.find_ancestor(exp.Condition)
                            predicate_condition = (
                                exp.and_(predicate_condition, condition)
                                if predicate_condition
                                else condition
                            )

                    if predicate_condition:
                        conditions[table] = (
                            exp.or_(conditions[table], predicate_condition)
                            if table in conditions
                            else predicate_condition
                        )

            for name, node in nodes.items():
                if name not in conditions:
                    continue
                predicate = conditions[name]

                if isinstance(node, exp.Join):
                    on = node.args.get("on")
                    node.set("on", exp.and_(predicate, on) if on else predicate)
                    if join_kind(node) == "CROSS":
                        node.set("kind", None)

                elif isinstance(node, exp.Select):
                    node.where(replace_aliases(node, predicate), copy=False)

    return expression


def nodes_for_predicate(predicate, scope):
    nodes = {}
    tables = exp.column_table_names(predicate)
    for table in tables:
        source = scope.sources[table]

        if isinstance(source, exp.Table):
            node = source.find_ancestor(exp.Join)
            if node:
                nodes[table] = node
        elif len(tables) == 1:
            nodes[table] = source.expression
    return nodes


def replace_aliases(source, predicate):
    aliases = {}

    for select in source.selects:
        if isinstance(select, exp.Alias):
            aliases[select.alias] = select.this
        else:
            aliases[select.name] = select

    def _replace_alias(column):
        # pylint: disable=cell-var-from-loop
        if isinstance(column, exp.Column) and column.name in aliases:
            return aliases[column.name]
        return column

    return predicate.transform(_replace_alias, copy=False)
