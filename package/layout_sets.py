from __future__ import annotations

from functools import cached_property
from typing import NotRequired, Self, TypedDict, TypeVar

import tree_sitter_javascript as ts_js
from tree_sitter import Language, Parser, Tree

from package.code import Code, Js
from package.json import GenericJson, GenericJsonFile, parse_json

from .iter import IterContainer

T = TypeVar("T", str, int, float, bool, None)
type ExpressionOr[T] = T | tuple[str, *tuple[ExpressionOr, ...]]


class ComponentJson(TypedDict):
    """Can have additional properties"""

    id: str
    type: str
    hidden: NotRequired[ExpressionOr[bool]]


class LayoutDataJson(TypedDict):
    hidden: NotRequired[ExpressionOr[bool]]
    layout: list[ComponentJson]


class LayoutJson(TypedDict):
    data: LayoutDataJson


class LayoutSetJson(TypedDict):
    id: str
    dataType: str
    tasks: list[str] | None


class LayoutSetsJson(TypedDict):
    sets: list[LayoutSetJson]


class Component(GenericJson[ComponentJson]):
    def __init__(self, json: ComponentJson | None, layout: Layout):
        super().__init__(json)
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


class Layout(GenericJsonFile[LayoutJson]):
    layout_set: LayoutSet

    def __init__(self, json: LayoutJson | None, file_path: str | None):
        super().__init__(json, file_path)
        self.components = (
            IterContainer(json["data"]["layout"]).map(lambda component_json: Component(component_json, self))
            if json is not None
            else IterContainer()
        )

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        return Layout(parse_json(data), file_path)

    def set_layout_set(self, layout_set: LayoutSet) -> Self:
        self.layout_set = layout_set
        return self


class LayoutSettings(GenericJsonFile):
    layout_set: LayoutSet

    def __init__(self, json: object | None, file_path: str | None):
        super().__init__(json, file_path)

    @staticmethod
    def empty():
        return LayoutSettings(None, None)

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        return LayoutSettings(parse_json(data), file_path)

    def set_layout_set(self, layout_set: LayoutSet) -> Self:
        self.layout_set = layout_set
        return self


class RuleConfiguration(GenericJsonFile):
    layout_set: LayoutSet

    def __init__(self, json: object | None, file_path: str | None):
        super().__init__(json, file_path)

    @staticmethod
    def empty():
        return RuleConfiguration(None, None)

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        return RuleConfiguration(parse_json(data), file_path)

    def set_layout_set(self, layout_set: LayoutSet) -> Self:
        self.layout_set = layout_set
        return self


JS_LANGUAGE = Language(ts_js.language())
js_parser = Parser(JS_LANGUAGE)


class RuleHandler:
    layout_set: LayoutSet

    def __init__(self, tree: Tree | None, file_path: str | None):
        self.tree = tree
        self.file_path = file_path

    @staticmethod
    def empty():
        return RuleHandler(None, None)

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        if data is None or len(data) == 0:
            return RuleHandler(None, file_path)
        return RuleHandler(js_parser.parse(data), file_path)

    def set_layout_set(self, layout_set: LayoutSet) -> Self:
        self.layout_set = layout_set
        return self

    @property
    def exists(self):
        return self.tree is not None and self.tree.root_node.text is not None

    def __repr__(self):
        if self.tree is not None and self.tree.root_node.text is not None:
            return self.tree.root_node.text.decode()
        return str(None)

    def __find(self, query: str) -> Code[Js] | None:
        if self.tree is None:
            return None
        matches = JS_LANGUAGE.query(query).captures(self.tree.root_node).get("output")
        if matches is None or len(matches) == 0 or matches[0].text is None:
            return None
        return Code.js(matches[0].text, self.file_path, matches[0].start_point.row + 1)

    def __iter(self, query: str) -> IterContainer[Code[Js]]:
        if self.tree is None:
            return IterContainer()
        matches = JS_LANGUAGE.query(query).captures(self.tree.root_node).get("output")
        if matches is None or len(matches) == 0:
            return IterContainer()
        return (
            IterContainer(matches)
            .filter(lambda match: match.text is not None)
            .map(lambda match: Code.js(match.text, self.file_path, match.start_point.row + 1))
        )

    def __find_in_object_declaration(self, variable_name: str, propery_name: str) -> Code[Js] | None:
        return self.__find(
            f"""
            (variable_declaration
                (variable_declarator 
                    name: (identifier) @variable.name
                    value: (object
                        (pair
                            key: (property_identifier) @prop.name
                            value: (_)
                            (#eq? @prop.name "{propery_name}")) @output)
                    (#eq? @variable.name "{variable_name}")))
            """
        )

    def __iter_object_declaration(self, variable_name: str) -> IterContainer[Code[Js]]:
        return self.__iter(
            f"""
            (variable_declaration
                (variable_declarator 
                    name: (identifier) @variable.name
                    value: (object
                        (pair
                            key: (property_identifier) @prop.name
                            value: (_)) @output)
                    (#eq? @variable.name "{variable_name}")))
            """
        )

    def rule(self, _name: str | GenericJson | None) -> Code[Js] | None:
        if (name := GenericJson.to_string(_name)) is None:
            return None
        return self.__find_in_object_declaration("ruleHandlerObject", name)

    def rule_helper(self, _name: str | GenericJson | None) -> Code[Js] | None:
        if (name := GenericJson.to_string(_name)) is None:
            return None
        return self.__find_in_object_declaration("ruleHandlerHelper", name)

    def conditional_rule(self, _name: str | GenericJson | None) -> Code[Js] | None:
        if (name := GenericJson.to_string(_name)) is None:
            return None
        return self.__find_in_object_declaration("conditionalRuleHandlerObject", name)

    def conditional_rule_helper(self, _name: str | GenericJson | None) -> Code[Js] | None:
        if (name := GenericJson.to_string(_name)) is None:
            return None
        return self.__find_in_object_declaration("conditionalRuleHandlerHelper", name)

    def rules(self) -> IterContainer[Code[Js]]:
        return self.__iter_object_declaration("ruleHandlerObject")

    def rule_helpers(self) -> IterContainer[Code[Js]]:
        return self.__iter_object_declaration("ruleHandlerHelper")

    def conditional_rules(self) -> IterContainer[Code[Js]]:
        return self.__iter_object_declaration("conditionalRuleHandlerObject")

    def conditional_rule_helpers(self) -> IterContainer[Code[Js]]:
        return self.__iter_object_declaration("conditionalRuleHandlerHelper")


class LayoutSet(GenericJson[LayoutSetJson]):
    def __init__(
        self,
        json: LayoutSetJson | None,
        layouts: IterContainer[Layout],
        layout_settings: IterContainer[LayoutSettings],
        rule_configuration: IterContainer[RuleConfiguration],
        rule_handler: IterContainer[RuleHandler],
        layout_sets: LayoutSets,
    ):
        super().__init__(json)
        self.layouts = layouts
        self.__layout_settings = layout_settings
        self.__rule_configuration = rule_configuration
        self.__rule_handler = rule_handler
        self.layout_sets = layout_sets

    # Lazy load by keeping it in an iterator until access
    @cached_property
    def layout_settings(self):
        return self.__layout_settings.first_or_default(LayoutSettings.empty().set_layout_set(self))

    @cached_property
    def rule_configuration(self):
        return self.__rule_configuration.first_or_default(RuleConfiguration.empty().set_layout_set(self))

    @cached_property
    def rule_handler(self):
        return self.__rule_handler.first_or_default(RuleHandler.empty().set_layout_set(self))

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


class LayoutSets(GenericJsonFile[LayoutSetsJson]):
    sets: IterContainer[LayoutSet]

    def __init__(self, json: LayoutSetsJson | None, file_path: str | None):
        super().__init__(json, file_path)

    @staticmethod
    def from_bytes(data: bytes | None, file_path: str | None):
        return LayoutSets(parse_json(data), file_path)

    @staticmethod
    def empty():
        return LayoutSets(None, None)
