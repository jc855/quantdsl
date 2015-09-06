from __future__ import division
import unittest
import datetime
import sys

import mock
import numpy
import scipy

from quantdsl import utc
from quantdsl.exceptions import DslSyntaxError
from quantdsl.priceprocess.blackscholes import BlackScholesPriceProcess
from quantdsl.semantics import DslExpression, String, Number, Date, TimeDelta, UnarySub, Add, Sub, Mult, Div, Pow, Mod, \
    FloorDiv, Max, On, LeastSquares, FunctionCall, FunctionDef, Name, If, IfExp, Compare, Module, DslNamespace
from quantdsl.services import dsl_eval, dsl_compile, dsl_parse
from quantdsl.syntax import DslParser
from quantdsl.infrastructure.runners.singlethread import SingleThreadedDependencyGraphRunner
from quantdsl.infrastructure.runners.multiprocess import MultiProcessingDependencyGraphRunner
from quantdsl.dependency_graph import DependencyGraph


def suite():
    return unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])


class TestDslParser(unittest.TestCase):

    def setUp(self):
        self.p = DslParser()

    def test_empty_string(self):
        self.assertTrue(isinstance(dsl_parse(""), Module))
        self.assertRaises(DslSyntaxError, dsl_compile, "")
        self.assertRaises(DslSyntaxError, dsl_eval, "")

    def assertDslExprTypeValue(self, dsl_source, expectedDslType, expectedDslValue, **compile_kwds):
        # Assumes dsl_source is just one statement.
        dsl_module = dsl_parse(dsl_source)

        # Check the parsed DSL can be rendered as a string that is equal to the original source.
        self.assertEqual(str(dsl_module).strip(), dsl_source.strip())

        # Check the statement's expression type.
        dsl_expr = dsl_module.body[0]
        self.assertIsInstance(dsl_expr, expectedDslType)

        # Compile the module into an simple DSL expression object (no variables or calls to function defs).
        dsl_expr = dsl_module.compile(compile_kwds)

        # Evaluate the compiled expression.
        self.assertEqual(dsl_expr.evaluate(), expectedDslValue)

    def test_num(self):
        self.assertDslExprTypeValue("0", Number, 0)
        self.assertDslExprTypeValue("5", Number, 5)
        self.assertDslExprTypeValue("-5", (Number, UnarySub), -5)
        self.assertDslExprTypeValue("5.1", Number, 5.1)
        self.assertDslExprTypeValue("-5.1", (Number, UnarySub), -5.1)

    def test_str(self):
        self.assertDslExprTypeValue("''", String, "")
        self.assertDslExprTypeValue("'#1'", String, "#1")

        # We can have comments too, but comments and trailing whitespaces are ignored.
        dsl = dsl_compile("'#1'  # This is a comment.")
        self.assertIsInstance(dsl, String)
        self.assertEqual(dsl.evaluate(), '#1')

    def test_name(self):
        self.assertDslExprTypeValue("foo", Name, "f", foo='f')
        self.assertDslExprTypeValue("foo", Name, 20, foo=20)

    def test_unaryop(self):
        self.assertDslExprTypeValue("-bar", UnarySub, -5, bar=5)
        self.assertDslExprTypeValue("-Max(1, 3)", UnarySub, -3)
        self.assertDslExprTypeValue("-Max(-1, -3)", UnarySub, 1)
        self.assertDslExprTypeValue("-Max(bar - 4, -9)", UnarySub, 8, bar=-4)

        # Check unsupported unary operators cause DSL errors.
        self.assertRaises(DslSyntaxError, dsl_parse, "~bar")

    def test_binop(self):
        self.assertDslExprTypeValue("5 + 2", Add, 7)
        self.assertDslExprTypeValue("5 - 2", Sub, 3)
        self.assertDslExprTypeValue("5 * 2", Mult, 10)
        self.assertDslExprTypeValue("5 / 2", Div, 2.5)
        self.assertDslExprTypeValue("5.0 / 2", Div, 2.5)
        self.assertDslExprTypeValue("5 / 2.0", Div, 2.5)
        self.assertDslExprTypeValue("5 // 2", FloorDiv, 2)
        self.assertDslExprTypeValue("5 ** 2", Pow, 25)
        self.assertDslExprTypeValue("5 % 2", Mod, 1)

        # Check unsupported binary operators cause DSL errors.
        self.assertRaises(DslSyntaxError, dsl_parse, "2 << 1")  # Bit shift left.
        self.assertRaises(DslSyntaxError, dsl_parse, "2 >> 1")  # Bit shift right.
        self.assertRaises(DslSyntaxError, dsl_parse, "2 & 1")  # Bitwise 'and'.
        self.assertRaises(DslSyntaxError, dsl_parse, "2 | 1")  # Complement
        self.assertRaises(DslSyntaxError, dsl_parse, "2 ^ 1")  # Bitwise exclusive or.

    def test_compare(self):
        self.assertDslExprTypeValue("1 == 1", Compare, True)
        self.assertDslExprTypeValue("1 == 2", Compare, False)
        self.assertDslExprTypeValue("2 != 1", Compare, True)
        self.assertDslExprTypeValue("1 != 1", Compare, False)
        self.assertDslExprTypeValue("1 < 2", Compare, True)
        self.assertDslExprTypeValue("1 < 1", Compare, False)
        self.assertDslExprTypeValue("1 <= 1", Compare, True)
        self.assertDslExprTypeValue("1 <= 2", Compare, True)
        self.assertDslExprTypeValue("1 <= 0", Compare, False)
        self.assertDslExprTypeValue("1 > 0", Compare, True)
        self.assertDslExprTypeValue("1 > 1", Compare, False)
        self.assertDslExprTypeValue("1 >= 1", Compare, True)
        self.assertDslExprTypeValue("2 >= 1", Compare, True)
        self.assertDslExprTypeValue("0 >= 1", Compare, False)

        # Multiple operators
        self.assertDslExprTypeValue("1 < 2 < 3", Compare, True)
        self.assertDslExprTypeValue("1 <= 2 <= 3", Compare, True)
        self.assertDslExprTypeValue("1 <= 2 >= 0", Compare, True)
        self.assertDslExprTypeValue("1 <= 2 >= 3", Compare, False)

    def test_ifexpr(self):
        self.assertDslExprTypeValue("foo if bar else 0", IfExp, 0, foo=0, bar=1)
        self.assertDslExprTypeValue("foo if bar else 0", IfExp, 2, foo=2, bar=1)
        self.assertDslExprTypeValue("foo if bar else 0", IfExp, 4, foo=4, bar=1)
        self.assertDslExprTypeValue("foo if bar else 0", IfExp, 0, foo=5, bar=0)

        self.assertDslExprTypeValue("6 if 1 else 7 if 1 else 8", IfExp, 6)
        self.assertDslExprTypeValue("6 if 0 else 7 if 1 else 8", IfExp, 7)
        self.assertDslExprTypeValue("6 if 0 else 7 if 0 else 8", IfExp, 8)

    def test_if(self):
        dsl_source = """
if bar:
    foo
else:
    0
"""
        self.assertDslExprTypeValue(dsl_source, If, 0, foo=0, bar=1)
        self.assertDslExprTypeValue(dsl_source, If, 2, foo=2, bar=1)
        self.assertDslExprTypeValue(dsl_source, If, 4, foo=4, bar=1)
        self.assertDslExprTypeValue(dsl_source, If, 0, foo=5, bar=0)

        dsl_source = """
if bar:
    foo
elif hee:
    haa
else:
    -1
"""
        self.assertDslExprTypeValue(dsl_source, If, 0, foo=0, bar=1, hee=1, haa=3)
        self.assertDslExprTypeValue(dsl_source, If, 2, foo=2, bar=1, hee=1, haa=3)
        self.assertDslExprTypeValue(dsl_source, If, 4, foo=4, bar=1, hee=1, haa=3)
        self.assertDslExprTypeValue(dsl_source, If, 3, foo=6, bar=0, hee=1, haa=3)
        self.assertDslExprTypeValue(dsl_source, If, -1, foo=6, bar=0, hee=0, haa=3)

    def test_call(self):
        self.assertDslExprTypeValue("Max(1, 2)", Max, 2)
        self.assertDslExprTypeValue("Max(Max(1, 2), 3)", Max, 3)
        self.assertDslExprTypeValue("Max(Max(Max(1, 2), 3), 4)", Max, 4)

        self.assertDslExprTypeValue("Max(1 + 4, 2)", Max, 5)

    def test_date(self):
        self.assertDslExprTypeValue("Date('2014-12-31')", Date, datetime.datetime(2014, 12, 31, tzinfo=utc))
        self.assertDslExprTypeValue("TimeDelta('1d')", TimeDelta, datetime.timedelta(1))

    def test_date_timedelta(self):
        # Some date arithmetic...
        dsl = dsl_compile("Date('2014-12-31') - TimeDelta('1d')")
        self.assertIsInstance(dsl, Sub)
        self.assertEqual(dsl.evaluate(), datetime.datetime(2014, 12, 30, tzinfo=utc))

        dsl = dsl_compile("Date('2014-12-29') + TimeDelta('1d')")
        self.assertIsInstance(dsl, Add)
        self.assertEqual(dsl.evaluate(), datetime.datetime(2014, 12, 30, tzinfo=utc))

        dsl = dsl_compile("2 * TimeDelta('1d')")
        self.assertIsInstance(dsl, Mult)
        self.assertEqual(dsl.evaluate(), datetime.timedelta(2))

    def test_date_comparisons(self):
        self.assertDslExprTypeValue("Date('2014-12-30') < Date('2014-12-31')", Compare, True)
        self.assertDslExprTypeValue("Date('2014-12-31') < Date('2014-12-30')", Compare, False)
        self.assertDslExprTypeValue("Date('2014-12-31') == Date('2014-12-31')", Compare, True)
        self.assertDslExprTypeValue("Date('2014-12-30') == Date('2014-12-31')", Compare, False)
        self.assertDslExprTypeValue("Date('2014-12-30') != Date('2014-12-31')", Compare, True)
        self.assertDslExprTypeValue("Date('2014-12-31') != Date('2014-12-31')", Compare, False)


    def test_on(self):
        dsl_source = "On('2012-01-01', 5)"
        dsl = dsl_compile(dsl_source)
        self.assertEqual(dsl_source, str(dsl))
        self.assertIsInstance(dsl, On)
        self.assertEqual(dsl.evaluate(), 5)

    def test_functiondef_simple(self):
        # Simple one-line body.
        dsl = dsl_compile("def a(): 1")
        self.assertIsInstance(dsl, FunctionDef)
        self.assertEqual(dsl.name, 'a')
        self.assertEqual(len(dsl.call_arg_names), 0)
        self.assertEqual(len(dsl.call_cache), 0)
        aExpr = dsl.apply()
        self.assertIsInstance(aExpr, Number)
        aValue = aExpr.evaluate()
        self.assertEqual(aValue, 1)

        # Check the call is in the cache.
        self.assertEqual(len(dsl.call_cache), 1)

        # Check a freshly parsed function def has a fresh call cache.
        dsl = dsl_compile("def a(): 1")
        self.assertEqual(len(dsl.call_cache), 0)

    def test_functiondef_dsl_max(self):
        # Simple one-line body.
        dsl = dsl_compile("def a(b): return Max(b, 2)")
        self.assertIsInstance(dsl, FunctionDef)
        self.assertEqual(dsl.name, 'a')
        self.assertEqual(dsl.call_arg_names[0], 'b')
        self.assertIsInstance(dsl.body, Max)
        self.assertIsInstance(dsl.body.left, Name)
        self.assertIsInstance(dsl.body.right, Number)
        self.assertEqual(dsl.body.evaluate(b=0), 2)
        self.assertEqual(dsl.body.evaluate(b=4), 4)
        a0 = dsl.apply(b=0)
        self.assertEqual(a0.evaluate(), 2)
        a4 = dsl.apply(b=4)
        self.assertEqual(a4.evaluate(), 4)

        # Return statement is optional, value of last expression is returned.
        dsl = dsl_compile("def a(b): Max(b, 2)")
        self.assertIsInstance(dsl, FunctionDef)
        self.assertEqual(dsl.name, 'a')
        self.assertEqual(dsl.apply(b=0).evaluate(), 2)
        self.assertEqual(dsl.apply(b=4).evaluate(), 4)

    def test_functiondef_dsl_max_conditional(self):
        # Conditional call.
        dsl = dsl_compile("def a(b): Max(b, 2) if b != 0 else 0")
        self.assertIsInstance(dsl, FunctionDef)
        self.assertEqual(dsl.name, 'a')
        self.assertEqual(dsl.call_arg_names[0], 'b')
        self.assertIsInstance(dsl.body, IfExp)
        self.assertEqual(dsl.body.test.evaluate(b=1), True)  # b != 0
        self.assertEqual(dsl.body.test.evaluate(b=0), False)
        self.assertEqual(dsl.body.body.evaluate(b=4), 4)     # Max(b, 2)
        self.assertEqual(dsl.body.body.evaluate(b=0), 2)

        a0 = dsl.apply(b=0)
        self.assertIsInstance(a0, Number)

        a1 = dsl.apply(b=1)
        self.assertIsInstance(a1, Max)
        self.assertIsInstance(a1.left, Number)
        self.assertIsInstance(a1.right, Number)
        self.assertEqual(a1.left.evaluate(), 1)
        self.assertEqual(a1.right.evaluate(), 2)
        self.assertEqual(a1.evaluate(), 2)

        a3 = dsl.apply(b=3)
        self.assertIsInstance(a3, Max)
        self.assertIsInstance(a3.left, Number)
        self.assertIsInstance(a3.right, Number)
        self.assertEqual(a3.left.evaluate(), 3)
        self.assertEqual(a3.right.evaluate(), 2)
        self.assertEqual(a3.evaluate(), 3)

    def test_functiondef_recursive_cached(self):
        # Recursive call.
        fib_def = dsl_compile("def fib(n): return fib(n-1) + fib(n-2) if n > 2 else n")

        # Check the parsed function def DSL object.
        self.assertIsInstance(fib_def, FunctionDef)
        self.assertFalse(fib_def.call_cache)
        self.assertEqual(fib_def.name, 'fib')
        self.assertEqual(fib_def.call_arg_names[0], 'n')
        self.assertIsInstance(fib_def.body, IfExp)
        self.assertEqual(fib_def.body.test.evaluate(n=3), True)
        self.assertEqual(fib_def.body.test.evaluate(n=2), False)
        self.assertIsInstance(fib_def.body.body, Add)
        self.assertIsInstance(fib_def.body.body.left, FunctionCall)
        self.assertIsInstance(fib_def.body.body.left.functionDefName, Name)
        self.assertIsInstance(fib_def.body.body.left.callArgExprs, list)
        self.assertIsInstance(fib_def.body.body.left.callArgExprs[0], Sub)
        self.assertIsInstance(fib_def.body.body.left.callArgExprs[0].left, Name)
        self.assertEqual(fib_def.body.body.left.callArgExprs[0].left.name, 'n')
        self.assertIsInstance(fib_def.body.body.left.callArgExprs[0].right, Number)
        self.assertEqual(fib_def.body.body.left.callArgExprs[0].right.value, 1)

        # Evaluate the function with different values of n.
        # n = 1
        fib_expr = fib_def.apply(n=1)
        self.assertIsInstance(fib_expr, Number)
        fib_value = fib_expr.evaluate()
        self.assertIsInstance(fib_value, (int, float))
        self.assertEqual(fib_value, 1)

        # Check call cache has one call.
        self.assertEqual(len(fib_def.call_cache), 1)

        # n = 2
        fib_expr = fib_def.apply(n=2)
        self.assertIsInstance(fib_expr, Number)
        fib_value = fib_expr.evaluate()
        self.assertIsInstance(fib_value, (int, float))
        self.assertEqual(fib_value, 2)

        # Check call cache has two calls.
        self.assertEqual(len(fib_def.call_cache), 2)

        # n = 3
        fib_expr = fib_def.apply(n=3)
        self.assertIsInstance(fib_expr, Add)
        self.assertIsInstance(fib_expr.left, Number)
        self.assertIsInstance(fib_expr.right, Number)
        fib_value = fib_expr.evaluate()
        self.assertIsInstance(fib_value, (int, float))
        self.assertEqual(fib_value, 3)

        # Check call cache has three calls.
        self.assertEqual(len(fib_def.call_cache), 3)

        # n = 4
        fib_expr = fib_def.apply(n=4)
        self.assertIsInstance(fib_expr, Add)
        self.assertIsInstance(fib_expr.left, Add)
        self.assertIsInstance(fib_expr.left.left, Number)
        self.assertEqual(fib_expr.left.left.evaluate(), 2)  # fib(2) -> 2
        self.assertIsInstance(fib_expr.left.right, Number)
        self.assertEqual(fib_expr.left.right.evaluate(), 1)
        self.assertIsInstance(fib_expr.right, Number)
        self.assertEqual(fib_expr.right.evaluate(), 2)  # fib(2) -> 2    *repeats
        # Check repeated calls have resulted in the same object.
        self.assertEqual(fib_expr.left.left, fib_expr.right)  # fib(2)

        fib_value = fib_expr.evaluate()
        self.assertIsInstance(fib_value, (int, float))
        self.assertEqual(fib_value, 5)

        # Check call cache has four calls.
        self.assertEqual(len(fib_def.call_cache), 4)

        # n = 5
        fib_expr = fib_def.apply(n=5)
        self.assertIsInstance(fib_expr, Add)  # fib(4) + fib(3)
        self.assertIsInstance(fib_expr.left, Add)  # fib(4) -> fib(3) + fib(2)
        self.assertIsInstance(fib_expr.left.left, Add)  # fib(3) -> fib(2) + fib(1)
        self.assertIsInstance(fib_expr.left.left.left, Number)  # fib(2) -> 2
        self.assertEqual(fib_expr.left.left.left.evaluate(), 2)
        self.assertIsInstance(fib_expr.left.left.right, Number)  # fib(1) -> 1
        self.assertEqual(fib_expr.left.left.right.evaluate(), 1)
        self.assertIsInstance(fib_expr.left.right, Number)  # fib(2) -> 2    *repeats
        self.assertEqual(fib_expr.left.right.evaluate(), 2)
        self.assertIsInstance(fib_expr.right, Add)  # fib(3) -> fib(2) + fib(1)    *repeats
        self.assertIsInstance(fib_expr.right.left, Number)  # fib(2) -> 2    *repeats
        self.assertEqual(fib_expr.right.left.evaluate(), 2)
        self.assertIsInstance(fib_expr.right.right, Number)  # fib(1) -> 1    *repeats
        self.assertEqual(fib_expr.right.right.evaluate(), 1)

        # Check repeated calls have resulted in the same object.
        self.assertEqual(fib_expr.right.right, fib_expr.left.left.right)  # fib(1)
        self.assertEqual(fib_expr.right.left, fib_expr.left.left.left)  # fib(2)
        self.assertEqual(fib_expr.left.right, fib_expr.left.left.left)  # fib(2)
        self.assertEqual(fib_expr.right, fib_expr.left.left)  # fib(3)

        fib_value = fib_expr.evaluate()
        self.assertIsInstance(fib_value, (int, float))
        self.assertEqual(fib_value, 8)

        # Check call cache has five calls.
        self.assertEqual(len(fib_def.call_cache), 5)

        # Just check call cache with fib(5) with fresh parser.
        fib_def = dsl_compile("def fib(n): return fib(n-1) + fib(n-2) if n > 2 else n")
        assert isinstance(fib_def, FunctionDef)
        self.assertEqual(len(fib_def.call_cache), 0)
        fib_expr = fib_def.apply(n=5)
        self.assertEqual(len(fib_def.call_cache), 5)
        self.assertEqual(fib_expr.evaluate(), 8)
        self.assertEqual(len(fib_def.call_cache), 5)

    def test_module_block(self):
        # Expression with one function def.
        dsl_source = """
def sqr(n):
    n ** 2
sqr(3)
"""
        dsl_module = dsl_parse(dsl_source)
        self.assertIsInstance(dsl_module, Module)
        self.assertEqual(str(dsl_module), dsl_source.strip())

        dsl_expr = dsl_compile(dsl_source)
        self.assertEqual(dsl_expr.evaluate(), 9)

        dsl_value = dsl_eval(dsl_source)
        self.assertEqual(dsl_value, 9)

        # Expression with two function defs.
        dsl_source = """
def add(a, b):
    a + b
def mul(a, b):
    a if b == 1 else add(a, mul(a, b - 1))
mul(3, 3)
"""
        dsl_module = dsl_parse(dsl_source)
        self.assertIsInstance(dsl_module, Module)
        self.assertEqual(str(dsl_module), dsl_source.strip())

        dsl_expr = dsl_compile(dsl_source)
#        self.assertEqual(str(dsl_expr), "")
        self.assertEqual(dsl_expr.evaluate(), 9)

        dsl_value = dsl_eval(dsl_source)
        self.assertEqual(dsl_value, 9)

    def test_parallel_fib(self):
        # Branching function calls.

        fib_index = 6
        expected_value = 13
        expected_len_stubbed_exprs = fib_index + 1

        dsl_source = """
def fib(n): fib(n-1) + fib(n-2) if n > 2 else n
fib(%d)
""" % fib_index

        # # Check the source works as a serial operation.
        # dsl_expr = dsl_parse(dsl_source, inParallel=False)
        # self.assertIsInstance(dsl_expr, Add)
        # dsl_value = dsl_expr.evaluate()
        # self.assertEqual(dsl_value, expected_value)

        # Check the source works as a parallel operation.
        dsl_expr = dsl_compile(dsl_source, is_parallel=True)

        # Expect an expression stack object.
        self.assertIsInstance(dsl_expr, DependencyGraph)

        # Remember the number of stubbed exprs - will check it after the value.
        actual_len_stubbed_exprs = len(dsl_expr.stubbed_exprs_data)

        # Evaluate the stack.
        runner = SingleThreadedDependencyGraphRunner(dsl_expr)
        dsl_value = runner.evaluate()

        # Check the value is expected.
        self.assertEqual(dsl_value, expected_value)

        # Check the number of stubbed exprs is expected.
        self.assertEqual(actual_len_stubbed_exprs, expected_len_stubbed_exprs)

        # Also check the runner call count is the same.
        self.assertEqual(runner.call_count, expected_len_stubbed_exprs)

    def test_parallel_american_option(self):
        # Branching function calls.

        expected_value = 5
        expected_len_stubbed_exprs = 7

        dsl_source = """
# NB using Max instead of Choice, to save development time.

def Option(date, strike, underlying, alternative):
    return Wait(date, Max(underlying - strike, alternative))

def American(starts, ends, strike, underlying, step):
    Option(starts, strike, underlying, 0) if starts == ends else \
    Option(starts, strike, underlying, American(starts + step, ends, strike, underlying, step))

American(Date('2012-01-01'), Date('2012-01-03'), 5, 10, TimeDelta('1d'))
"""

        dsl_expr = dsl_compile(dsl_source, is_parallel=True)

        # Expect an expression stack object.
        self.assertIsInstance(dsl_expr, DependencyGraph)

        # Remember the number of stubbed exprs - will check it after the value.
        actual_len_stubbed_exprs = len(dsl_expr.stubbed_exprs_data)

        # Evaluate the stack.
        image = mock.Mock()
        image.price_process.get_duration_years.return_value = 1
        kwds = {
            'image': image,
            'interest_rate': 0,
            'present_time': datetime.datetime(2011, 1, 1, tzinfo=utc),
            'dependency_graph_runner_class': SingleThreadedDependencyGraphRunner,
        }
        dsl_value = SingleThreadedDependencyGraphRunner(dsl_expr).evaluate(**kwds)

        # Check the value is expected.
        self.assertEqual(dsl_value, expected_value)

        # Check the number of stubbed exprs is expected.
        self.assertEqual(actual_len_stubbed_exprs, expected_len_stubbed_exprs)

    def test_parallel_swing_option(self):
        # Branching function calls.

        expected_value = 20
        expected_len_stubbed_exprs = 7

        dsl_source = """
def Swing(starts, ends, underlying, quantity):
    if (quantity != 0) and (starts < ends):
        return Max(
            Swing(starts + TimeDelta('1d'), ends, underlying, quantity-1) \
            + Fixing(starts, underlying),
            Swing(starts + TimeDelta('1d'), ends, underlying, quantity)
        )
    else:
        return 0
Swing(Date('2011-01-01'), Date('2011-01-03'), 10, 5)
"""

        dsl_expr = dsl_compile(dsl_source, is_parallel=True)

        # Remember the number of stubbed exprs - will check it after the value.
        actual_len_stubbed_exprs = len(dsl_expr)

        # Evaluate the stack.
        image = mock.Mock()
        image.price_process.get_duration_years.return_value = 1
        kwds = {
            'image': image,
            'interest_rate': 0,
            'present_time': datetime.datetime(2011, 1, 1),
            'dependency_graph_runner_class': SingleThreadedDependencyGraphRunner,
        }

        dsl_value = SingleThreadedDependencyGraphRunner(dsl_expr).evaluate(**kwds)

        # Check the value is expected.
        self.assertEqual(dsl_value, expected_value)

        # Check the number of stubbed exprs is expected.
        self.assertEqual(actual_len_stubbed_exprs, expected_len_stubbed_exprs)

    def test_multiprocessed_swing_option(self):
        # Branching function calls.

        expected_value = 20
        expected_len_stubbed_exprs = 7

        dsl_source = """
def Swing(starts, ends, underlying, quantity):
    if (quantity == 0) or (starts >= ends):
        0
    else:
        Wait(starts, Choice(
            Swing(starts + TimeDelta('1d'), ends, underlying, quantity - 1) + Fixing(starts, underlying),
            Swing(starts + TimeDelta('1d'), ends, underlying, quantity)
        ))
Swing(Date('2011-01-01'), Date('2011-01-03'), 10, 50)
"""

        dsl_expr = dsl_compile(dsl_source, is_parallel=True)
        assert isinstance(dsl_expr, DependencyGraph)

        # Remember the number of stubbed exprs - will check it after the value.
        actual_len_stubbed_exprs = len(dsl_expr.stubbed_exprs_data)

        kwds = {
            'interest_rate': 0,
            'present_time': datetime.datetime(2011, 1, 1, tzinfo=utc),
            'all_market_prices': {
                '#1': dict(
                    [(datetime.datetime(2011, 1, 1, tzinfo=utc) + datetime.timedelta(1) * i, numpy.array([10]*2000))
                        for i in range(0, 10)])  # NB Need enough days to cover the date range in the dsl_source.
            },
            # 'pool_size': 5,
            # 'dependency_graph_runner_class': MultiProcessingDependencyGraphRunner,
        }

        # Evaluate the dependency graph.
        dsl_value = MultiProcessingDependencyGraphRunner(dsl_expr).evaluate(**kwds)

        if hasattr(dsl_value, 'mean'):
            dsl_value = dsl_value.mean()

        # Check the value is expected.
        self.assertEqual(dsl_value, expected_value)

        # Check the number of stubbed exprs is expected.
        self.assertEqual(actual_len_stubbed_exprs, expected_len_stubbed_exprs)


class MockImage(object):

    def __init__(self, price_process):
        self.price_process = price_process


class MockPriceProcess(object): pass


class TestLeastSquares(unittest.TestCase):

    DECIMALS = 12

    def assertFit(self, fixture_x, fixture_y, expected_values):
        assert expected_values != None
        ls = LeastSquares(scipy.array(fixture_x), scipy.array(fixture_y))
        fit_data = ls.fit()
        for i, expected_value in enumerate(expected_values):
            fit_value = round(fit_data[i], self.DECIMALS)
            msg = "expected_values value: %s, fit value: %s, expected_values data: %s, fit data: %s" % (
                expected_value, fit_value, expected_values, fit_data)
            self.assertEqual(expected_value, fit_value, msg)

    def test_fit1(self):
        self.assertFit(
            fixture_x=[
                [0, 1, 2],
                [3, 4, 5]],
            fixture_y=[1, 1, 1],
            expected_values=[1, 1, 1],
        )

    def test_fit2(self):
        self.assertFit(
            fixture_x=[[0, 1, 2], [3, 4, 5]],
            fixture_y=[0, 1, 2],
            expected_values=[0, 1, 2],
        )


class DslTestCase(unittest.TestCase):

    def assertValuation(self, dsl_source=None, expected_value=None, expected_delta=None, expected_gamma=None,
            tolerance_value=0.05, tolerance_delta = 0.1, tolerance_gamma=0.1):

        # Check option value.
        observation_date = datetime.datetime(2011, 1, 1, tzinfo=utc)
        estimated_value = self.calc_value(dsl_source, observation_date)
        self.assertTolerance(estimated_value, expected_value, tolerance_value)

        # Todo: Reinstate the delta tests.
        return
        # Check deltas.
        markets = self.pricer.get_markets()
        if not markets:
            assert self.expected_delta == None
            return
        market = list(markets)[0]
        # Check option delta.
        estimated_delta = self.pricer.calc_delta(market)
        self.assertTolerance(estimated_delta, expected_delta, tolerance_delta)

        # Todo: Decide what to do with gamma (too much noise to pass tests consistently at the mo). Double-side differentials?
        # Check option gamma.
        #estimatedGamma = self.pricer.calcGamma(market)
        #roundedGamma = round(estimatedGamma, self.DECIMALS)
        #expected_gamma = round(self.expected_gamma, self.DECIMALS)
        #msg = "Value: %s  Expected: %s" % (roundedGamma, expected_gamma)
        #self.assertEqual(roundedGamma, expected_gamma, msg)

    def assertTolerance(self, estimated, expected, tolerance):
        upper = expected + tolerance
        lower = expected - tolerance
        assert lower <= estimated <= upper, "Estimated '%s' not close enough to expected '%s' (tolerance '%s')." % (estimated, expected, tolerance)

    def calc_value(self, dsl_source, observation_time):
        # Todo: Rename 'allRvs' to 'simulatedPrices'?
        evaluation_kwds = DslNamespace({
            'observation_time': observation_time,
            'interest_rate': '2.5',
            'market_calibration': {
                '#1-LAST-PRICE': 10,
                '#1-ACTUAL-HISTORICAL-VOLATILITY': 50,
                '#2-LAST-PRICE': 10,
                '#2-ACTUAL-HISTORICAL-VOLATILITY': 50,
                '#1-#2-CORRELATION': 0.0,
                'NBP-LAST-PRICE': 10,
                'NBP-ACTUAL-HISTORICAL-VOLATILITY': 50,
                'TTF-LAST-PRICE': 11,
                'TTF-ACTUAL-HISTORICAL-VOLATILITY': 40,
                'BRENT-LAST-PRICE': 90,
                'BRENT-ACTUAL-HISTORICAL-VOLATILITY': 60,
                'NBP-TTF-CORRELATION': 0.4,
                'BRENT-TTF-CORRELATION': 0.5,
                'BRENT-NBP-CORRELATION': 0.3,
            },
            'path_count': 200000,
        })
        return dsl_eval(dsl_source, evaluation_kwds=evaluation_kwds)['mean']


        dsl_expr = dsl_compile(dsl_source)

        evaluation_kwds = DslNamespace({
            'observation_time': observation_time,
            'present_time': observation_time,
            'interest_rate': '2.5',
            'calibration': {
                '#1-LAST-PRICE': 10,
                '#1-ACTUAL-HISTORICAL-VOLATILITY': 50,
                '#2-LAST-PRICE': 10,
                '#2-ACTUAL-HISTORICAL-VOLATILITY': 50,
            },
            'allRvs': BlackScholesPriceProcess().getAllRvs(dsl_expr, observation_time, path_count=100000),
        })
        assert isinstance(dsl_expr, DslExpression)
        value = dsl_expr.evaluate(**evaluation_kwds)
        if hasattr(value, 'mean'):
            value = value.mean()
        return value


class TestDslMarket(DslTestCase):

    def testValuation(self):
        specification = "Market('#1')"
        self.assertValuation(specification, 10, 1, 0)


class TestDslFixing(DslTestCase):

    def testValuation(self):
        specification = "Fixing(Date('2012-01-01'), Market('#1'))"
        self.assertValuation(specification, 10, 1, 0)


class TestDslWait(DslTestCase):

    def testValuation(self):
        specification = "Wait(Date('2012-01-01'), Market('#1'))"
        self.assertValuation(specification, 9.753, 0.975, 0)


class TestDslSettlement(DslTestCase):

    def testValuation(self):
        specification = "Settlement(Date('2012-01-01'), Market('#1'))"
        self.assertValuation(specification, 9.753, 0.975, 0)


class TestDslChoice(DslTestCase):

    def testValuation(self):
        specification = "Fixing(Date('2012-01-01'), Choice( Market('#1') - 9, 0))"
        self.assertValuation(specification, 2.416, 0.677, 0.07)


class TestDslMax(DslTestCase):

    def testValuation(self):
        specification = "Fixing(Date('2012-01-01'), Max(Market('#1'), Market('#2')))"
        self.assertValuation(specification, 12.766, 0.636, 0)
        #self.assertValuation(specification, 11.320, 0.636, 0)


class TestDslAdd(DslTestCase):

    def testValuation(self):
        specification = "10 + Market('#1')"
        self.assertValuation(specification, 20, 1, 0)

    def testValuation(self):
        specification = "10 + Market('#2')"
        self.assertValuation(specification, 20, 1, 0)


class TestDslSubtract(DslTestCase):

    def testValuation(self):
        specification = "Market('#1') - 10"
        self.assertValuation(specification, 0, 1, 0)


class TestDslMultiply(DslTestCase):

    def testValuation(self):
        specification = "Market('#1') * Market('#2')"
        self.assertValuation(specification, 100, 10, 0)


class TestDslDivide(DslTestCase):

    def testValuation(self):
        specification = "Market('#1') / 10"
        self.assertValuation(specification, 1, 0.1, 0)


class TestDslIdenticalFixings(DslTestCase):

    def testValuation(self):
        specification = """
Fixing(Date('2012-01-01'), Market('#1')) - Fixing(Date('2012-01-01'), Market('#1'))
"""
        self.assertValuation(specification, 0, 0, 0)


class TestDslBrownianIncrements(DslTestCase):

    def testValuation(self):
        specification = """
Wait(
    Date('2012-03-15'),
    Max(
        Fixing(
            Date('2012-01-01'),
            Market('#1')
        ) /
        Fixing(
            Date('2011-01-01'),
            Market('#1')
        ),
        1.0
    ) -
    Max(
        Fixing(
            Date('2013-01-01'),
            Market('#1')
        ) /
        Fixing(
            Date('2012-01-01'),
            Market('#1')
        ),
        1.0
    )
)"""
        self.assertValuation(specification, 0, 0, 0)


class TestDslUncorrelatedMarkets(DslTestCase):

    def testValuation(self):
        specification = """
Max(
    Fixing(
        Date('2012-01-01'),
        Market('#1')
    ) *
    Fixing(
        Date('2012-01-01'),
        Market('#2')
    ) / 10.0,
    0.0
) - Max(
    Fixing(
        Date('2013-01-01'),
        Market('#1')
    ), 0
)"""
        self.assertValuation(specification, 0, 0, 0, 0.07, 0.2, 0.2)  # Todo: Figure out why the delta sometimes evaluates to 1 for a period of time and then


class TestDslCorrelatedMarkets(DslTestCase):

    def testValuation(self):
        specification = """
Max(
    Fixing(
        Date('2012-01-01'),
        Market('TTF')
    ) *
    Fixing(
        Date('2012-01-01'),
        Market('NBP')
    ) / 10.0,
    0.0
) - Max(
    Fixing(
        Date('2013-01-01'),
        Market('TTF')
    ), 0
)"""
        self.assertValuation(specification, 0.92, 0, 0, 0.15, 0.2, 0.2)


class TestDslFutures(DslTestCase):

    def testValuation(self):
        specification = """
Wait( Date('2012-01-01'),
    Market('#1') - 9
) """
        self.assertValuation(specification, 0.9753, 0.9753, 0)


class TestDslEuropean(DslTestCase):

    def testValuation(self):
        specification = "Wait(Date('2012-01-01'), Choice(Market('#1') - 9, 0))"
        self.assertValuation(specification, 2.356, 0.660, 0.068)


class TestDslBermudan(DslTestCase):

    def testValuation(self):
        specification = """
Fixing( Date('2011-06-01'), Choice( Market('#1') - 9,
    Fixing( Date('2012-01-01'), Choice( Market('#1') - 9, 0))
))
"""
        self.assertValuation(specification, 2.401, 0.677, 0.0001)


class TestDslSumContracts(DslTestCase):

    def testValuation(self):
        specification = """
Fixing(
    Date('2011-06-01'),
    Choice(
        Market('#1') - 9,
        Fixing(
            Date('2012-01-01'),
            Choice(
                Market('#1') - 9,
                0
            )
        )
    )
) + Fixing(
    Date('2011-06-01'),
    Choice(
        Market('#1') - 9,
        Fixing(
            Date('2012-01-01'),
            Choice(
                Market('#1') - 9,
                0
            )
        )
    )
)
"""
        self.assertValuation(specification, 4.812, 2 * 0.677, 2*0.07, 0.09, 0.2, 0.2)


class TestDslAddition(DslTestCase):

    def testValuation2(self):
        specification = """
Fixing( Date('2012-01-01'),
    Max(Market('#1') - 9, 0) + Market('#1') - 9
)
"""
        self.assertValuation(specification, 3.416, 1.677, 0.07, 0.07, 0.2, 0.2)


class TestDslFunctionDefSwing(DslTestCase):

    def testValuation(self):
        specification = """
def Swing(starts, ends, underlying, quantity):
    if (quantity != 0) and (starts < ends):
        return Choice(
            Swing(starts + TimeDelta('1d'), ends, underlying, quantity-1) \
            + Fixing(starts, underlying),
            Swing(starts + TimeDelta('1d'), ends, underlying, quantity)
        )
    else:
        return 0
Swing(Date('2012-01-01'), Date('2012-01-03'), Market('#1'), 2)
"""
        self.assertValuation(specification, 20.0, 2.0, 0.07, 0.06, 0.2, 0.2)


class TestDslFunctionDefOption(DslTestCase):

    def testValuation(self):
        specification = """
def Option(date, strike, x, y):
    return Wait(date, Choice(x - strike, y))
Option(Date('2012-01-01'), 9, Underlying(Market('#1')), 0)
"""
        self.assertValuation(specification, 2.356, 0.660, 0.068, 0.04, 0.2, 0.2)


class TestDslFunctionDefEuropean(DslTestCase):

    def testValuation(self):
        specification = """
def Option(date, strike, underlying, alternative):
    return Wait(date, Choice(underlying - strike, alternative))

def European(date, strike, underlying):
    return Option(date, strike, underlying, 0)

European(Date('2012-01-01'), 9, Market('#1'))
"""
        self.assertValuation(specification, 2.356, 0.660, 0.068, 0.04, 0.2, 0.2)


class TestDslFunctionDefAmerican(DslTestCase):

    def testValuation(self):
        specification = """
def Option(date, strike, underlying, alternative):
    return Wait(date, Choice(underlying - strike, alternative))

def American(starts, ends, strike, underlying, step):
    Option(starts, strike, underlying, 0) if starts == ends else \
    Option(starts, strike, underlying, American(starts + step, ends, strike, underlying, step))

American(Date('2012-01-01'), Date('2012-01-3'), 9, Market('#1'), TimeDelta('1d'))
"""
        self.assertValuation(specification, 2.356, 0.660, 0.068, 0.04, 0.2, 0.2)
