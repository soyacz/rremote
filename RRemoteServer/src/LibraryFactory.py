from __future__ import print_function

import inspect
import os
import re
import select
import signal
import sys
import threading
import traceback

if sys.version_info < (3,):
    from SimpleXMLRPCServer import SimpleXMLRPCServer
    from StringIO import StringIO
    from xmlrpclib import Binary, ServerProxy
    from collections import Mapping

    PY2, PY3 = True, False
else:
    from io import StringIO
    from xmlrpc.client import Binary, ServerProxy
    from xmlrpc.server import SimpleXMLRPCServer
    from collections.abc import Mapping

    PY2, PY3 = False, True
    unicode = str
    long = int


__all__ = ["RobotRemoteServer", "stop_remote_server", "test_remote_server"]
__version__ = "1.1.1.dev1"

BINARY = re.compile("[\x00-\x08\x0B\x0C\x0E-\x1F]")
NON_ASCII = re.compile("[\x80-\xff]")


def RemoteLibraryFactory(library):
    library = library()
    if inspect.ismodule(library):
        return StaticRemoteLibrary(library)
    get_keyword_names = dynamic_method(library, "get_keyword_names")
    if not get_keyword_names:
        return StaticRemoteLibrary(library)
    run_keyword = dynamic_method(library, "run_keyword")
    if not run_keyword:
        return HybridRemoteLibrary(library, get_keyword_names)
    return DynamicRemoteLibrary(library, get_keyword_names, run_keyword)


def dynamic_method(library, underscore_name):
    tokens = underscore_name.split("_")
    camelcase_name = tokens[0] + "".join(t.title() for t in tokens[1:])
    for name in underscore_name, camelcase_name:
        method = getattr(library, name, None)
        if method and is_function_or_method(method):
            return method
    return None


def is_function_or_method(item):
    return inspect.isfunction(item) or inspect.ismethod(item)


class StaticRemoteLibrary(object):
    def __init__(self, library):
        self._library = library
        self._names, self._robot_name_index = self._get_keyword_names(library)

    def _get_keyword_names(self, library):
        names = []
        robot_name_index = {}
        for name, kw in inspect.getmembers(library):
            if is_function_or_method(kw):
                if getattr(kw, "robot_name", None):
                    names.append(kw.robot_name)
                    robot_name_index[kw.robot_name] = name
                elif name[0] != "_":
                    names.append(name)
        return names, robot_name_index

    def get_keyword_names(self):
        return self._names

    def run_keyword(self, name, args, kwargs=None):
        kw = self._get_keyword(name)
        return KeywordRunner(kw).run_keyword(args, kwargs)

    def _get_keyword(self, name):
        if name in self._robot_name_index:
            name = self._robot_name_index[name]
        return getattr(self._library, name)

    def get_keyword_arguments(self, name):
        if __name__ == "__init__":
            return []
        kw = self._get_keyword(name)
        args, varargs, kwargs, defaults = inspect.getargspec(kw)
        if inspect.ismethod(kw):
            args = args[1:]  # drop 'self'
        if defaults:
            args, names = args[: -len(defaults)], args[-len(defaults) :]
            args += ["%s=%s" % (n, d) for n, d in zip(names, defaults)]
        if varargs:
            args.append("*%s" % varargs)
        if kwargs:
            args.append("**%s" % kwargs)
        return args

    def get_keyword_documentation(self, name):
        if name == "__intro__":
            source = self._library
        elif name == "__init__":
            source = self._get_init(self._library)
        else:
            source = self._get_keyword(name)
        return inspect.getdoc(source) or ""

    def _get_init(self, library):
        if inspect.ismodule(library):
            return None
        init = getattr(library, "__init__", None)
        return init if self._is_valid_init(init) else None

    def _is_valid_init(self, init):
        if not init:
            return False
        # https://bitbucket.org/pypy/pypy/issues/2462/
        if "PyPy" in sys.version:
            if PY2:
                return init.__func__ is not object.__init__.__func__
            return init is not object.__init__
        return is_function_or_method(init)

    def get_keyword_tags(self, name):
        keyword = self._get_keyword(name)
        return getattr(keyword, "robot_tags", [])


class HybridRemoteLibrary(StaticRemoteLibrary):
    def __init__(self, library, get_keyword_names):
        StaticRemoteLibrary.__init__(self, library)
        self.get_keyword_names = get_keyword_names


class DynamicRemoteLibrary(HybridRemoteLibrary):
    def __init__(self, library, get_keyword_names, run_keyword):
        HybridRemoteLibrary.__init__(self, library, get_keyword_names)
        self._run_keyword = run_keyword
        self._supports_kwargs = self._get_kwargs_support(run_keyword)
        self._get_keyword_arguments = dynamic_method(library, "get_keyword_arguments")
        self._get_keyword_documentation = dynamic_method(
            library, "get_keyword_documentation"
        )
        self._get_keyword_tags = dynamic_method(library, "get_keyword_tags")

    def _get_kwargs_support(self, run_keyword):
        spec = inspect.getargspec(run_keyword)
        return len(spec.args) > 3  # self, name, args, kwargs=None

    def run_keyword(self, name, args, kwargs=None):
        args = [name, args, kwargs] if kwargs else [name, args]
        return KeywordRunner(self._run_keyword).run_keyword(args)

    def get_keyword_arguments(self, name):
        if self._get_keyword_arguments:
            return self._get_keyword_arguments(name)
        if self._supports_kwargs:
            return ["*varargs", "**kwargs"]
        return ["*varargs"]

    def get_keyword_documentation(self, name):
        if self._get_keyword_documentation:
            return self._get_keyword_documentation(name)
        return ""

    def get_keyword_tags(self, name):
        if self._get_keyword_tags:
            return self._get_keyword_tags(name)
        return []


class KeywordRunner(object):
    def __init__(self, keyword):
        self._keyword = keyword

    def run_keyword(self, args, kwargs=None):
        args = self._handle_binary(args)
        kwargs = self._handle_binary(kwargs or {})
        result = KeywordResult()
        with StandardStreamInterceptor() as interceptor:
            try:
                return_value = self._keyword(*args, **kwargs)
            except Exception:
                result.set_error(*sys.exc_info())
            else:
                try:
                    result.set_return(return_value)
                except Exception:
                    result.set_error(*sys.exc_info()[:2])
                else:
                    result.set_status("PASS")
        result.set_output(interceptor.output)
        return result.data

    def _handle_binary(self, arg):
        # No need to compare against other iterables or mappings because we
        # only get actual lists and dicts over XML-RPC. Binary cannot be
        # a dictionary key either.
        if isinstance(arg, list):
            return [self._handle_binary(item) for item in arg]
        if isinstance(arg, dict):
            return dict((key, self._handle_binary(arg[key])) for key in arg)
        if isinstance(arg, Binary):
            return arg.data
        return arg


class StandardStreamInterceptor(object):
    def __init__(self):
        self.output = ""
        self.origout = sys.stdout
        self.origerr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        try:
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
            close = [sys.stdout, sys.stderr]
            sys.stdout = self.origout
            sys.stderr = self.origerr
            for stream in close:
                stream.close()
            if stdout and stderr:
                if not stderr.startswith(
                    ("*TRACE*", "*DEBUG*", "*INFO*", "*HTML*", "*WARN*", "*ERROR*")
                ):
                    stderr = "*INFO* %s" % stderr
                if not stdout.endswith("\n"):
                    stdout += "\n"
            self.output = stdout + stderr
        except AttributeError:
            self.output = f"RRemote is not thread safe - needs fixing"
            #  some ideas: https://bytes.com/topic/python/answers/36067-thread-specific-sys-stdout
            # https://stackoverflow.com/questions/14890997/redirect-stdout-to-a-file-only-for-a-specific-thread


class KeywordResult(object):
    _generic_exceptions = (AssertionError, RuntimeError, Exception)

    def __init__(self):
        self.data = {"status": "FAIL"}

    def set_error(self, exc_type, exc_value, exc_tb=None):
        self.data["error"] = self._get_message(exc_type, exc_value)
        if exc_tb:
            self.data["traceback"] = self._get_traceback(exc_tb)
        continuable = self._get_error_attribute(exc_value, "CONTINUE")
        if continuable:
            self.data["continuable"] = continuable
        fatal = self._get_error_attribute(exc_value, "EXIT")
        if fatal:
            self.data["fatal"] = fatal

    def _get_message(self, exc_type, exc_value):
        name = exc_type.__name__
        message = self._get_message_from_exception(exc_value)
        if not message:
            return name
        if exc_type in self._generic_exceptions or getattr(
            exc_value, "ROBOT_SUPPRESS_NAME", False
        ):
            return message
        return "%s: %s" % (name, message)

    def _get_message_from_exception(self, value):
        # UnicodeError occurs if message contains non-ASCII bytes
        try:
            msg = unicode(value)
        except UnicodeError:
            msg = " ".join(self._str(a, handle_binary=False) for a in value.args)
        return self._handle_binary_result(msg)

    def _get_traceback(self, exc_tb):
        # Latest entry originates from this module so it can be removed
        entries = traceback.extract_tb(exc_tb)[1:]
        trace = "".join(traceback.format_list(entries))
        return "Traceback (most recent call last):\n" + trace

    def _get_error_attribute(self, exc_value, name):
        return bool(getattr(exc_value, "ROBOT_%s_ON_FAILURE" % name, False))

    def set_return(self, value):
        value = self._handle_return_value(value)
        if value != "":
            self.data["return_"] = value

    def _handle_return_value(self, ret):
        if isinstance(ret, (str, unicode, bytes)):
            return self._handle_binary_result(ret)
        if isinstance(ret, (int, long, float)):
            return ret
        if isinstance(ret, Mapping):
            return dict(
                (self._str(key), self._handle_return_value(value))
                for key, value in ret.items()
            )
        try:
            return [self._handle_return_value(item) for item in ret]
        except TypeError:
            return self._str(ret)

    def _handle_binary_result(self, result):
        if not self._contains_binary(result):
            return result
        if not isinstance(result, bytes):
            try:
                result = result.encode("ASCII")
            except UnicodeError:
                raise ValueError("Cannot represent %r as binary." % result)
        # With IronPython Binary cannot be sent if it contains "real" bytes.
        if sys.platform == "cli":
            result = str(result)
        return Binary(result)

    def _contains_binary(self, result):
        if PY3:
            return isinstance(result, bytes) or BINARY.search(result)
        return (
            isinstance(result, bytes)
            and NON_ASCII.search(result)
            or BINARY.search(result)
        )

    def _str(self, item, handle_binary=True):
        if item is None:
            return ""
        if not isinstance(item, (str, unicode, bytes)):
            item = unicode(item)
        if handle_binary:
            item = self._handle_binary_result(item)
        return item

    def set_status(self, status):
        self.data["status"] = status

    def set_output(self, output):
        if output:
            self.data["output"] = self._handle_binary_result(output)
