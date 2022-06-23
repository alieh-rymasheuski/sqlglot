import itertools

from sqlglot.helper import while_changing
from sqlglot.expressions import FALSE, NULL, TRUE
from sqlglot.generator import Generator
import sqlglot.expressions as exp


GENERATOR = Generator(normalize=True, identify=True)


def simplify(expression):
    """
    Rewrite sqlglot AST to simplify expressions.

    Example:
        >>> import sqlglot
        >>> expression = sqlglot.parse_one("TRUE AND TRUE")
        >>> simplify(expression).sql()
        'TRUE'

    Args:
        expression (sqlglot.Expression): expression to simplify
    Returns:
        sqlglot.Expression: simplified expression
    """

    def _simplify(expression, root=True):
        node = expression
        node = uniq_sort(node)
        node = absorb_and_eliminate(node)
        exp.replace_children(node, lambda e: _simplify(e, False))
        node = simplify_equality(node)
        node = simplify_not(node)
        node = flatten(node)
        node = simplify_conjunctions(node)
        node = remove_compliments(node)
        node.parent = expression.parent
        node = simplify_parens(node)
        if root:
            expression.replace(node)
        return node

    expression = while_changing(expression, _simplify)
    remove_where_true(expression)
    return expression


def simplify_equality(expression):
    if isinstance(expression, exp.EQ):
        left = expression.left
        right = expression.right

        if NULL in (left, right):
            return NULL
        if left == right:
            return TRUE
        if (
            isinstance(left, exp.Literal)
            and isinstance(right, exp.Literal)
            and left.is_string
            and right.is_string
            and left != right
        ):
            return FALSE
    return expression


def simplify_not(expression):
    if isinstance(expression, exp.Not):
        if always_true(expression.this):
            return FALSE
        if expression.this == FALSE:
            return TRUE
        if isinstance(expression.this, exp.Not):
            # double negation
            # NOT NOT x -> x
            return expression.this.this
    return expression


def flatten(expression):
    """
    A AND (B AND C) -> A AND B AND C
    A OR (B OR C) -> A OR B OR C
    """
    if isinstance(expression, exp.Connector):
        for node in expression.args.values():
            child = node.unnest()
            if isinstance(child, expression.__class__):
                node.replace(child)
    return expression


def simplify_conjunctions(expression):
    if isinstance(expression, exp.Connector):
        left = expression.left
        right = expression.right

        if left == right:
            return left

        if isinstance(expression, exp.And):
            if NULL in (left, right):
                return NULL
            if FALSE in (left, right):
                return FALSE
            if always_true(left) and always_true(right):
                return TRUE
            if always_true(left):
                return right
            if always_true(right):
                return left
        elif isinstance(expression, exp.Or):
            if always_true(left) or always_true(right):
                return TRUE
            if left == FALSE and right == FALSE:
                return FALSE
            if (
                (left == NULL and right == NULL)
                or (left == NULL and right == FALSE)
                or (left == FALSE and right == NULL)
            ):
                return NULL
            if left == FALSE:
                return right
            if right == FALSE:
                return left
    return expression


def remove_compliments(expression):
    """
    Removing compliments.

    A AND NOT A -> FALSE
    A OR NOT A -> TRUE
    """
    if isinstance(expression, exp.Connector):
        compliment = FALSE if isinstance(expression, exp.And) else TRUE

        for a, b in itertools.permutations(expression.flatten(), 2):
            if is_complement(a, b):
                return compliment
    return expression


def uniq_sort(expression):
    """
    Uniq and sort a connector.

    C AND A AND B AND B -> A AND B AND C
    """
    if isinstance(expression, exp.Connector):
        result_func = exp.and_ if isinstance(expression, exp.And) else exp.or_
        flattened = tuple(expression.flatten())
        deduped = {GENERATOR.generate(e): e for e in flattened}
        arr = tuple(deduped.items())

        # check if the operands are already sorted, if not sort them
        # A AND C AND B -> A AND B AND C
        for i, (sql, e) in enumerate(arr[1:]):
            if sql < arr[i][0]:
                expression = result_func(*(deduped[sql] for sql in sorted(deduped)))
                break
        else:
            # we didn't have to sort but maybe we need to dedup
            if len(deduped) < len(flattened):
                expression = result_func(*deduped.values())

    return expression


def absorb_and_eliminate(expression):
    """
    absorption:
        A AND (A OR B) -> A
        A OR (A AND B) -> A
        A AND (NOT A OR B) -> A AND B
        A OR (NOT A AND B) -> A OR B
    elimination:
        (A AND B) OR (A AND NOT B) -> A
        (A OR B) AND (A OR NOT B) -> A
    """
    if isinstance(expression, exp.Connector):
        kind = exp.Or if isinstance(expression, exp.And) else exp.And

        for a, b in itertools.permutations(expression.flatten(), 2):
            if isinstance(a, kind):
                aa, ab = a.unnest_operands()

                # absorb
                if is_complement(b, aa):
                    aa.replace(exp.TRUE if kind == exp.And else exp.FALSE)
                elif is_complement(b, ab):
                    ab.replace(exp.TRUE if kind == exp.And else exp.FALSE)
                elif (set(b.flatten()) if isinstance(b, kind) else {b}) < set(
                    a.flatten()
                ):
                    a.replace(exp.FALSE if kind == exp.And else exp.TRUE)
                elif isinstance(b, kind):
                    # eliminate
                    rhs = b.unnest_operands()
                    ba, bb = rhs

                    if aa in rhs and (is_complement(ab, ba) or is_complement(ab, bb)):
                        a.replace(aa)
                        b.replace(aa)
                    elif ab in rhs and (is_complement(aa, ba) or is_complement(aa, bb)):
                        a.replace(ab)
                        b.replace(ab)

    return expression


def is_complement(a, b):
    return isinstance(b, exp.Not) and b.this == a


def simplify_parens(expression):
    if (
        isinstance(expression, exp.Paren)
        and not isinstance(expression.this, exp.Select)
        and (
            not isinstance(expression.parent, (exp.Condition, exp.Binary))
            or not isinstance(expression.this, exp.Binary)
        )
    ):
        return expression.this
    return expression


def remove_where_true(expression):
    for where in expression.find_all(exp.Where):
        if always_true(where.this):
            where.parent.set("where", None)
    for join in expression.find_all(exp.Join):
        if always_true(join.args.get("on")):
            join.set("kind", "CROSS")
            join.set("on", None)


def always_true(expression):
    return expression == TRUE or isinstance(expression, exp.Literal)
