from __future__ import annotations
from functools import cache
from typing import NotRequired, TypedDict, Unpack, cast
import tree_sitter_c_sharp as ts_cs
from tree_sitter import Language, Parser

from package.code import Code, Cs
from package.iter import IterContainer

CS_LANGUAGE = Language(ts_cs.language())
cs_parser = Parser(CS_LANGUAGE)


class ClassArgs(TypedDict):
    name: NotRequired[str | None]
    implements: NotRequired[str | None]


class CsCode(Code[Cs]):
    def __init__(self, content: str | bytes | None = None, file_path: str | None = None, start_line: int = 1):
        super().__init__("cs", content, file_path, start_line)

    def root_node(self):
        if self.bytes is None:
            return None
        return cs_parser.parse(self.bytes).root_node

    @cache
    def query(self, query: str) -> list[CsCode]:
        root_node = self.root_node()
        if root_node is None:
            return []
        matches = CS_LANGUAGE.query(query).captures(root_node).get("output")
        if matches is None or len(matches) == 0:
            return []
        return (
            IterContainer(matches)
            .filter(lambda match: match.text is not None)
            .map(lambda match: CsCode(match.text, self.file_path, match.start_point.row + 1))
        ).list

    def class_declarations(self, **kwargs: Unpack[ClassArgs]) -> IterContainer[CsCode]:
        name, implements = None, None
        if "name" in kwargs and (name := kwargs["name"]) is None:
            return IterContainer()
        if "implements" in kwargs and (implements := kwargs["implements"]) is None:
            return IterContainer()

        name_restriction = f'(#eq? @class.name "{name}")' if name is not None else ""
        implements_restriction = (
            f"""
            (base_list
                (identifier) @interface.name
                (#eq? @interface.name "{implements}"))
            """
            if implements is not None
            else ""
        )

        return IterContainer(
            self.query(
                f"""
                (class_declaration
                    name: (identifier) @class.name
                    {name_restriction}
                    {implements_restriction}) @output
            """
            )
        )


class AppServiceArgs(TypedDict):
    interface_name: NotRequired[str | None]


class ProgramCs(CsCode):
    def __init__(self, content: str | bytes | None = None, file_path: str | None = None, start_line: int = 1):
        super().__init__(content, file_path, start_line)

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
        matches = self.query(
            f"""
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
                """
        )
        return (
            IterContainer(matches)
            .map(lambda code: cast(str, code.text))
            .filter(lambda service_name: service_name != None)
        )
