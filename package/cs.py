from __future__ import annotations
from itertools import starmap
from functools import cache, cached_property
from typing import NotRequired, TypedDict, Unpack, cast, Sequence
import tree_sitter_c_sharp as ts_cs
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from package.code import Code, Cs, Lines, build_sequence_predicate, build_set_predicate, escape_predicate
from package.iter import IterContainer

CS_LANGUAGE = Language(ts_cs.language())
cs_parser = Parser(CS_LANGUAGE)


class CsCode(Code[Cs]):
    def __init__(
        self,
        content: bytes | None = None,
        file_path: str | None = None,
        remote_url: str | None = None,
        lines: Lines = None,
        node: Node | None = None,
    ):
        super().__init__("cs", content, file_path, remote_url, lines)
        self.__node = node

    @cached_property
    def node(self):
        if self.__node is not None:
            return self.__node
        if self.bytes is None:
            return None
        return cs_parser.parse(self.bytes).root_node

    @cache
    @staticmethod
    def build_query(query_str: str) -> Query:
        """Building the query is expensive so it should not be done for every iteration"""
        return CS_LANGUAGE.query(query_str)

    def query(self, query_str: str) -> list[CsCode]:
        if self.node is None:
            return []
        matches = QueryCursor(CsCode.build_query(query_str)).captures(self.node).get("output")
        if matches is None or len(matches) == 0:
            return []
        return (
            IterContainer(matches)
            .filter(lambda node: node.text is not None)
            .map(
                lambda node: CsCode(
                    node.text, self.file_path, self.remote_url, (node.start_point.row + 1, node.end_point.row + 1), node
                )
            )
        ).list

    class ClassArgs(TypedDict):
        name: NotRequired[str]
        implements: NotRequired[Sequence[str]]
        modifiers: NotRequired[Sequence[str]]

    def class_declarations(self, **kwargs: Unpack[ClassArgs]) -> IterContainer[CsCode]:
        name, implements, modifiers = kwargs.get("name"), kwargs.get("implements"), kwargs.get("modifiers")

        name_restriction = f'(#eq? @class.name "{name}")' if name is not None else ""

        interfaces = (
            "\n".join(
                map(
                    # TODO: Should this pattern be used elsewhere?
                    lambda interface: f"""
                        {build_generic_identifier('interface.name')}
                        (#any-eq? @interface.name "{interface}")""",
                    implements,
                )
            )
            if implements is not None
            else None
        )

        implements_restriction = (
            f"""
            (base_list
                {interfaces})
            """
            if interfaces is not None
            else ""
        )

        modifiers_restriction = (
            "\n".join(
                map(
                    lambda modifier: f"""
                        (modifier) @modifier.name
                        (#any-eq? @modifier.name "{modifier}")""",
                    modifiers,
                )
            )
            if modifiers is not None
            else ""
        )

        return IterContainer(self.query(f"""
                (class_declaration
                    {modifiers_restriction}
                    name: (identifier) @class.name
                    {name_restriction}
                    {implements_restriction}) @output
                """))

    class MethodArgs(TypedDict):
        name: NotRequired[str]
        returns: NotRequired[str]
        modifiers: NotRequired[Sequence[str]]
        parameter_types: NotRequired[Sequence[str]]

    def method_declarations(self, **kwargs: Unpack[MethodArgs]) -> IterContainer[CsCode]:
        name, returns, modifiers, parameter_types = (
            kwargs.get("name"),
            kwargs.get("returns"),
            kwargs.get("modifiers"),
            kwargs.get("parameter_types"),
        )

        name_restriction = f'(#eq? @method.name "{name}")' if name is not None else ""
        returns_restriction = f'(#eq? @method.returns "{returns}")' if returns is not None else ""
        modifiers_restriction = (
            "\n".join(
                map(
                    lambda modifier: f"""
                        (modifier) @modifier.name
                        (#any-eq? @modifier.name "{modifier}")""",
                    modifiers,
                )
            )
            if modifiers is not None
            else ""
        )
        parameter_types_restriction = (
            "\n".join(
                map(
                    lambda parameter_type: f"""
                        (parameter
                            type: (identifier) @parameter.type)
                            (#any-eq? @parameter.type "{parameter_type}")""",
                    parameter_types,
                )
            )
            if parameter_types is not None
            else ""
        )

        return IterContainer(self.query(f"""
                (method_declaration
                    {modifiers_restriction}
                    returns: (_) @method.returns
                    {returns_restriction}
                    name: (identifier) @method.name
                    {name_restriction}
                    parameters: (parameter_list
                    {parameter_types_restriction})) @output
                """))

    class FunctionInvocationArgs(TypedDict):
        name: NotRequired[str]
        positional_arguments: NotRequired[Sequence[str | None]]
        named_arguments: NotRequired[Sequence[tuple[str | None, str | None]]]

    def function_invocations(self, **kwargs: Unpack[FunctionInvocationArgs]) -> IterContainer[CsCode]:
        name, positional_arguments, named_arguments = (
            kwargs.get("name"),
            kwargs.get("positional_arguments"),
            kwargs.get("named_arguments"),
        )

        name_restriction = f'(#eq? @function.name "{name}")' if name is not None else ""
        positional_arguments_restriction = (
            build_sequence_predicate(
                starmap(
                    lambda idx, argument: f"""
                    (argument
                        !name) @pos_argument.{idx}
                    """
                    + (f'(#eq? @pos_argument.{idx} "{escape_predicate(argument)}")' if argument is not None else ""),
                    enumerate(positional_arguments),
                )
            )
            if positional_arguments is not None
            else ""
        )
        named_arguments_restriction = (
            build_set_predicate(
                starmap(
                    lambda idx, name_arg: f"""
                    (argument
                        name: (identifier) @name_argument.name.{idx}
                        (_) @name_argument.value.{idx}
                    """
                    + (f'(#eq? @name_argument.name.{idx} "{name_arg[0]}")' if name_arg[0] is not None else "")
                    + (
                        f'\n(#eq? @name_argument.value.{idx} "{escape_predicate(name_arg[1])}")'
                        if name_arg[1] is not None
                        else ""
                    )
                    + ")",
                    enumerate(named_arguments),
                ),
                "name_argument",
            )
            if named_arguments is not None
            else ""
        )

        return IterContainer(self.query(f"""
                (invocation_expression
                    function: {build_generic_member_access_identifier('function.name')}
                    {name_restriction}
                    arguments: (argument_list
                    {positional_arguments_restriction}
                    {named_arguments_restriction})) @output
                """))

    class ObjectArgs(TypedDict):
        type: NotRequired[str | None]
        fields: NotRequired[Sequence[str]]

    def object_creations(self, **kwargs: Unpack[ObjectArgs]) -> IterContainer[CsCode]:
        type, fields = None, kwargs.get("fields")
        if "type" in kwargs and (type := kwargs["type"]) is None:
            return IterContainer()

        type_restriction = f'(#eq? @object.type "{type}")' if type is not None else ""

        assignments = (
            "\n".join(
                map(
                    lambda name: f"""
                    (assignment_expression
                        left: (identifier) @field.name
                        (#any-eq? @field.name "{name}"))""",
                    fields,
                )
            )
            if fields is not None
            else None
        )
        initializer_restriction = (
            f"""
            initializer: (initializer_expression
                {assignments})
             """
            if assignments is not None
            else ""
        )

        return IterContainer(self.query(f"""
                (object_creation_expression
                    type: (identifier) @object.type
                    {type_restriction}
                    {initializer_restriction}) @output
                """))

    class IdentifierArgs(TypedDict):
        name: str

    def identifiers(self, **kwargs: Unpack[IdentifierArgs]) -> IterContainer[CsCode]:
        name = kwargs.get("name")
        return IterContainer(self.query(f"""
                ((identifier) @name
                (#eq? @name "{name}")) @output
                """))


class AppServiceArgs(TypedDict):
    interface_name: NotRequired[str | None]


class ProgramCs(CsCode):
    def __init__(self, content: bytes | None = None, file_path: str | None = None, remote_url: str | None = None):
        super().__init__(content, file_path, remote_url)

    def custom_app_services(self, **kwargs: Unpack[AppServiceArgs]) -> IterContainer[str]:
        interface_name = None
        if "interface_name" in kwargs and (interface_name := kwargs["interface_name"]) is None:
            return IterContainer()

        interface_name_restriction = f'(#eq? @interface.name "{interface_name}")' if interface_name is not None else ""

        # This may be a bit overkill
        # It first looks for the RegisterCustomAppServices function with a IServiceCollection argument
        # In the body, it looks for a statement like:
        # services.Add.*<interface_name, .*>(.*);
        # where "services" matches the argument of type IServiceCollection
        # and "interface_name" matches the kwarg if specified
        matches = self.query(f"""
            (local_function_statement
                name: (identifier) @register_func.name
                (#eq? @register_func.name "RegisterCustomAppServices")
                parameters: (parameter_list
                    (parameter
                        type: (identifier) @service_collection.type
                        (#eq? @service_collection.type "IServiceCollection")
                        name: (identifier) @service_collection.name))
                body: (block
                    (expression_statement
                        (invocation_expression
                            function: (member_access_expression
                                expression: (identifier) @member.name
                                (#eq? @member.name @service_collection.name)
                                name: (generic_name
                                    (identifier) @method.name
                                    (#match? @method.name "^Add.+")
                                    (type_argument_list
                                        (identifier) @interface.name
                                        {interface_name_restriction}
                                        (identifier) @output)))
                            arguments: (_)))))
                """)
        return (
            IterContainer(matches)
            .map(lambda code: cast(str, code.text))
            .filter(lambda service_name: service_name != None)
        )


def build_generic_identifier(capture_name: str) -> str:
    return f"""
            [
                (identifier) @{capture_name}
                (generic_name
                    (identifier) @{capture_name})
            ]
            """


def build_generic_member_access_identifier(capture_name: str) -> str:
    return f"""
            [
                (identifier) @{capture_name}
                (generic_name
                    (identifier) @{capture_name})
                (member_access_expression
                    name: (identifier) @{capture_name})
                (member_access_expression
                    name: (generic_name
                        (identifier) @{capture_name}))
            ]
            """
