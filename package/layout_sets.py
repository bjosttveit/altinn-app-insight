from __future__ import annotations

from functools import cache, cached_property
from typing import NotRequired, Self, TypedDict, Unpack

import tree_sitter_javascript as ts_js
from tree_sitter import Language, Parser

from package.code import Code, Js
from package.json import Json

from .iter import IterContainer


class ComponentJson(TypedDict):
    id: str
    type: str


class LayoutDataJson(TypedDict):
    layout: list[ComponentJson]


class LayoutJson(TypedDict):
    data: LayoutDataJson


class LayoutSetJson(TypedDict):
    id: str
    dataType: str
    tasks: list[str] | None


class LayoutSetsJson(TypedDict):
    sets: list[LayoutSetJson]


class Component(Json[ComponentJson]):
    def __init__(self, json: bytes | ComponentJson | None, file_path: str | None, layout: Layout):
        super().__init__(json, file_path)
        self.layout = layout

    @property
    def id(self):
        if self.json is None:
            return None
        return self.json["id"]

    @property
    def type(self):
        if self.json is None:
            return None
        return self.json["type"]


class Layout(Json[LayoutJson]):
    layout_set: LayoutSet

    def __init__(self, json: bytes | LayoutJson | None = None, file_path: str | None = None):
        super().__init__(json, file_path)
        self.components = (
            IterContainer(self.json["data"]["layout"]).map(
                lambda component_json: Component(component_json, file_path, self)
            )
            if self.json is not None
            else IterContainer()
        )

    def set_layout_set(self, layout_set: LayoutSet) -> Self:
        self.layout_set = layout_set
        return self


class LayoutSettings(Json):
    layout_set: LayoutSet

    def __init__(self, json: bytes | object | None = None, file_path: str | None = None):
        super().__init__(json, file_path)

    def set_layout_set(self, layout_set: LayoutSet) -> Self:
        self.layout_set = layout_set
        return self


class RuleConfiguration(Json):
    layout_set: LayoutSet

    def __init__(self, json: bytes | object | None = None, file_path: str | None = None):
        super().__init__(json, file_path)

    def set_layout_set(self, layout_set: LayoutSet) -> Self:
        self.layout_set = layout_set
        return self


JS_LANGUAGE = Language(ts_js.language())
js_parser = Parser(JS_LANGUAGE)


class RuleArgs(TypedDict):
    name: NotRequired[str | Json | None]


class RuleHandler(Code[Js]):
    layout_set: LayoutSet

    def __init__(self, content: str | bytes | None = None, file_path: str | None = None, start_line: int = 1):
        super().__init__("js", content, file_path, start_line)

    def set_layout_set(self, layout_set: LayoutSet) -> Self:
        self.layout_set = layout_set
        return self

    def root_node(self):
        if self.bytes is None:
            return None
        return js_parser.parse(self.bytes).root_node

    @cache
    def query(self, query: str) -> list[Code[Js]]:
        root_node = self.root_node()
        if root_node is None:
            return []
        matches = JS_LANGUAGE.query(query).captures(root_node).get("output")
        if matches is None or len(matches) == 0:
            return []
        return (
            IterContainer(matches)
            .filter(lambda match: match.text is not None)
            .map(lambda match: Code.js(match.text, self.file_path, match.start_point.row + 1))
        ).list

    def object_declarations(self, variable_name: str | None = None, propery_name: str | None = None):
        variable_name_restriction = f'(#eq? @variable.name "{variable_name}")' if variable_name is not None else ""
        propery_name_restriction = f'(#eq? @prop.name "{propery_name}")' if propery_name is not None else ""

        return IterContainer(
            self.query(
                f"""
                (variable_declaration
                    (variable_declarator 
                        name: (identifier) @variable.name
                        {variable_name_restriction}
                        value: (object
                            (pair
                                key: (property_identifier) @prop.name
                                {propery_name_restriction}
                                value: (_)) @output)))
                """
            )
        )

    def rules(self, **kwargs: Unpack[RuleArgs]) -> IterContainer[Code[Js]]:
        name = None
        if "name" in kwargs and (name := Json.to_string(kwargs["name"])) is None:
            return IterContainer()
        return self.object_declarations("ruleHandlerObject", name)

    def rule_helpers(self, **kwargs: Unpack[RuleArgs]) -> IterContainer[Code[Js]]:
        name = None
        if "name" in kwargs and (name := Json.to_string(kwargs["name"])) is None:
            return IterContainer()
        return self.object_declarations("ruleHandlerHelper", name)

    def conditional_rules(self, **kwargs: Unpack[RuleArgs]) -> IterContainer[Code[Js]]:
        name = None
        if "name" in kwargs and (name := Json.to_string(kwargs["name"])) is None:
            return IterContainer()
        return self.object_declarations("conditionalRuleHandlerObject", name)

    def conditional_rule_helpers(self, **kwargs: Unpack[RuleArgs]) -> IterContainer[Code[Js]]:
        name = None
        if "name" in kwargs and (name := Json.to_string(kwargs["name"])) is None:
            return IterContainer()
        return self.object_declarations("conditionalRuleHandlerHelper", name)


class LayoutSet(Json[LayoutSetJson]):
    def __init__(
        self,
        json: LayoutSetJson | None,
        layouts: IterContainer[Layout],
        layout_settings: IterContainer[LayoutSettings],
        rule_configuration: IterContainer[RuleConfiguration],
        rule_handler: IterContainer[RuleHandler],
        layout_sets: LayoutSets,
    ):
        super().__init__(json, layout_sets.file_path)
        self.layouts = layouts
        self.__layout_settings = layout_settings
        self.__rule_configuration = rule_configuration
        self.__rule_handler = rule_handler
        self.layout_sets = layout_sets

    # Lazy load by keeping it in an iterator until access
    @cached_property
    def layout_settings(self):
        return self.__layout_settings.first_or_default(LayoutSettings().set_layout_set(self))

    @cached_property
    def rule_configuration(self):
        return self.__rule_configuration.first_or_default(RuleConfiguration().set_layout_set(self))

    @cached_property
    def rule_handler(self):
        return self.__rule_handler.first_or_default(RuleHandler().set_layout_set(self))

    @property
    def id(self):
        if self.json is None:
            return None
        return self.json["id"]

    @property
    def data_type(self):
        if self.json is None:
            return None
        return self.json["dataType"]

    @property
    def tasks(self):
        if self.json is None:
            return None
        return self.json["tasks"]


class LayoutSets(Json[LayoutSetsJson]):
    sets: IterContainer[LayoutSet]

    def __init__(self, json: bytes | LayoutSetsJson | None = None, file_path: str | None = None):
        super().__init__(json, file_path)
