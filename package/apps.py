from __future__ import annotations

from typing import TYPE_CHECKING, overload, Any

from numpy.typing import ArrayLike

from package.code import Code, Html, Xml
from package.cs import CsCode, ProgramCs
from package.html import tabulate_html

from .iter import IterContainer, IterController
from .json import Appsettings, Json
from .layout_sets import (
    Component,
    Layout,
    LayoutSet,
    LayoutSetJson,
    LayoutSets,
    LayoutSettings,
    RuleConfiguration,
    RuleHandler,
)
from .plotting import setup_plot
from .repo import Environment, VersionLock
from .version import Version

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

import json
import re
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from functools import cached_property
from io import BufferedReader
from pathlib import Path
from typing import Callable, TypeVar, cast
from zipfile import ZipFile

from IPython.display import display_html
from tabulate import tabulate


class App:
    def __init__(self, env: Environment, org: str, app: str, app_dir: Path):
        self.env: Environment = env
        self.org = org
        self.app = app
        self.app_dir = app_dir
        self.data = {}

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def file_name(self):
        return f"{self.key}.zip"

    @property
    def file_path(self):
        return self.app_dir.joinpath(self.file_name)

    def __repr__(self):
        headers = ["Env", "Org", "App", *self.data_keys]
        data = [[self.env, self.org, self.app, *self.data_values]]
        return tabulate(data, headers=headers, tablefmt="simple_grid")

    def with_data(self, data: dict[str, object]) -> App:
        if self.open:
            raise Exception("Attempted to copy an `App` object while open for reading, this could cause weird issues!")
        app = copy(self)
        app.data = data
        return app

    @cached_property
    def data_keys(self) -> list[str]:
        return list(self.data.keys())

    @cached_property
    def data_values(self) -> list[object]:
        return list(self.data.values())

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    # Uses a context manager to make sure any file operations are closed
    # Does not open any files yet, this happens lazily only when needed
    @staticmethod
    def wrap_open_app[T](__func: Callable[[App], T]) -> Callable[[App], T]:
        def func(app: App):
            with app as open_app:
                result = __func(open_app)
                result.__repr__()  # Make sure iterators are consumed while we are open
                return result

        return func

    # Creates a copy of the App instance with the data returned in the callback
    @staticmethod
    def wrap_with_data(__func: Callable[[App], dict[str, object]]) -> Callable[[App], App]:
        def func(app: App):
            return app.with_data(__func(app))

        return func

    __file: BufferedReader | None = None
    __zip_file: ZipFile | None = None

    def __enter__(self):
        self.open = True
        return self

    def __exit__(self, type, value, traceback):
        self.open = False
        if self.__zip_file is not None:
            self.__zip_file.close()
            self.__zip_file = None
        if self.__file is not None:
            self.__file.close()
            self.__file = None

    @property
    def content(self) -> ZipFile:
        if not self.open:
            raise Exception("Tried to access `App.content` without first opening the file using the `with` keyword")
        if self.__zip_file is None:
            self.__file = open(self.file_path, "rb")
            self.__zip_file = ZipFile(self.__file)
        return self.__zip_file

    @cached_property
    def files(self) -> list[str]:
        return self.content.namelist()

    def file_exists(self, file_pattern: str):
        return IterContainer(self.files).filter(lambda path: re.search(file_pattern, path) is not None).is_not_empty

    def files_matching(self, file_pattern: str):
        return (
            IterContainer(self.files)
            .filter(lambda path: re.search(file_pattern, path) is not None)
            .map(lambda path: (self.content.read(path), path))
        )

    @cached_property
    def application_metadata(self) -> Json:
        return (
            self.files_matching(r"/App/config/applicationmetadata.json$")
            .map(lambda args: Json(*args))
            .first_or_default(Json())
        )

    @cached_property
    def layout_sets(self) -> LayoutSets:
        layout_sets = (
            self.files_matching(r"/App/ui/layout-sets.json$")
            .map(lambda args: LayoutSets(*args))
            .first_or_default(LayoutSets())
        )

        # Get the json of each layout set (if applicable), base path to the layout set, and path to layout files
        layout_set_info = cast(
            IterContainer[tuple[LayoutSetJson | None, str, str]],
            (
                # Multiple layout sets, read paths from layout-sets.json
                IterContainer(layout_sets.json["sets"]).map(lambda set_json: (set_json, f"/App/ui/{set_json['id']}/"))
                if layout_sets.json is not None
                # Only one layout set, directly in /ui/
                else IterContainer([(None, "/App/ui/")])
            ).starmap(
                lambda set_json, base_path: (
                    # Multiple layout files, in /ui/(.+/)?layouts/
                    (set_json, base_path, multi_path)
                    if self.file_exists(multi_path := rf"{base_path}layouts/.+\.json$")
                    else (
                        # Single layout file, in /ui/FormLayout.json
                        (set_json, base_path, single_path)
                        if self.file_exists(single_path := rf"{base_path}FormLayout\.json$")
                        # No layout files
                        else None
                    )
                )
            )
            # Ignore layout sets with no layout files
            .filter(lambda values: values is not None),
        )

        return layout_sets.set_sets(
            layout_set_info.starmap(
                lambda set_json, base_path, layouts_path: (
                    layout_set := LayoutSet(
                        set_json,
                        # Layouts
                        self.files_matching(layouts_path)
                        .map(lambda args: Layout(*args).set_layout_set(layout_set))
                        .filter(lambda layout: layout.exists),
                        # LayoutSettings
                        self.files_matching(rf"{base_path}Settings\.json$").map(
                            lambda args: LayoutSettings(*args).set_layout_set(layout_set)
                        ),
                        # RuleConfiguration
                        self.files_matching(rf"{base_path}RuleConfiguration\.json$").map(
                            lambda args: RuleConfiguration(*args).set_layout_set(layout_set)
                        ),
                        # RuleHandler
                        self.files_matching(rf"{base_path}RuleHandler\.js$").map(
                            lambda args: RuleHandler(*args).set_layout_set(layout_set)
                        ),
                        # LayoutSets
                        layout_sets,
                    )
                )
            )
        )

    @cached_property
    def layouts(self) -> IterContainer[Layout]:
        return self.layout_sets.sets.flat_map(lambda set: set.layouts)

    @cached_property
    def components(self) -> IterContainer[Component]:
        return self.layout_sets.sets.flat_map(lambda set: set.layouts.flat_map(lambda layout: layout.components))

    @cached_property
    def layout_settings(self) -> IterContainer[LayoutSettings]:
        return self.layout_sets.sets.map(lambda set: set.layout_settings).filter(
            lambda layout_settings: layout_settings.exists
        )

    @cached_property
    def rule_configurations(self) -> IterContainer[RuleConfiguration]:
        return self.layout_sets.sets.map(lambda set: set.rule_configuration).filter(
            lambda rule_configuration: rule_configuration.exists
        )

    @cached_property
    def rule_handlers(self) -> IterContainer[RuleHandler]:
        return self.layout_sets.sets.map(lambda set: set.rule_handler).filter(lambda rule_handler: rule_handler.exists)

    @cached_property
    def app_settings(self) -> IterContainer[Appsettings]:
        return (
            self.files_matching(r"/App/appsettings(\.[^.]+)?\.json$")
            .map(lambda args: Appsettings(*args))
            .filter(lambda file: file.exists)
        )

    @cached_property
    def cs(self) -> IterContainer[CsCode]:
        return self.files_matching(r"/App/.*\.cs$").map(lambda args: CsCode(*args)).filter(lambda file: file.exists)

    @cached_property
    def program_cs(self) -> ProgramCs:
        return self.files_matching(r"/App/Program.cs$").map(lambda args: ProgramCs(*args)).first_or_default(ProgramCs())

    @cached_property
    def index_cshtml(self) -> Code[Html]:
        return (
            self.files_matching(r"/App/views/Home/Index.cshtml$")
            .map(lambda args: Code.html(*args))
            .first_or_default(Code.html())
        )

    @cached_property
    def csproj(self) -> IterContainer[Code[Xml]]:
        return (
            self.files_matching(r"/App/[^/]+.csproj$")
            .map(lambda args: Code.xml(*args))
            .filter(lambda file: file.exists)
        )

    @cached_property
    def frontend_version(self) -> Version:
        return Version(
            self.index_cshtml.find(
                r'src="https://altinncdn.no/toolkits/altinn-app-frontend/([a-zA-Z0-9\-.]+)/altinn-app-frontend.js"', 1
            )
        )

    @cached_property
    def backend_version(self) -> Version:
        return Version(
            self.csproj.flat_map(
                lambda file: file.find_all(
                    r'(?i)Include="Altinn\.App\.(Core|Api|Common)(\.Experimental)?"\s*Version="([a-zA-Z0-9\-.]+)"', 3
                )
            ).first
        )


class Apps(IterController[App]):
    def __init__(
        self,
        apps: IterContainer[App],
        groupings: dict[str, object] = {},
        selector: dict[str, Callable[[Apps], object]] = {},
    ):
        super().__init__(apps)
        self.groupings = groupings
        self.selector = selector

    def with_iterable(self, iterable: IterContainer[App]):
        return Apps(iterable, self.groupings, self.selector)

    def with_selector(self, data: dict[str, Callable[[Apps], object]]) -> Apps:
        return Apps(self.i, self.groupings, data)

    @staticmethod
    def wrap_with_selector(selector: dict[str, Callable[[Apps], object]]) -> Callable[[Apps], Apps]:
        def func(apps: Apps):
            return apps.with_selector(selector)

        return func

    def table(self):
        if self.length == 0:
            print("Count: 0")
            return

        headers = ["Env", "Org", "App", *self.list[0].data_keys]
        data = [[app.env, app.org, app.app, *app.data_values] for app in self.list]
        table = tabulate_html(data, headers=headers)
        display_html(table)
        print(f"Count: {self.length}")

    def __repr__(self):
        if self.length == 0:
            return "Count: 0"

        headers = ["Env", "Org", "App", *self.list[0].data_keys]
        data = [[app.env, app.org, app.app, *app.data_values] for app in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

    @classmethod
    def init(cls, apps_dir: Path = Path("./data"), max_open_files=100) -> Apps:
        lock_path = Path.joinpath(apps_dir, ".apps.lock.json")
        if not lock_path.exists():
            print("Failed to locate lock file")
            exit(1)

        with open(lock_path, "r") as f:
            lock_file: VersionLock = json.load(f)

        apps: list[App] = []
        for lock_data in lock_file.values():
            if lock_data["status"] == "success":
                apps.append(App(lock_data["env"], lock_data["org"], lock_data["app"], apps_dir))

        executor = ThreadPoolExecutor(max_workers=max_open_files)

        return cls(IterContainer(apps, executor))

    @cached_property
    def group_keys(self) -> list[str]:
        return list(self.groupings.keys())

    @cached_property
    def group_values(self) -> list[object]:
        return list(self.groupings.values())

    @cached_property
    def data_keys(self) -> list[str]:
        return list(self.selector.keys())

    @cached_property
    def data_values(self) -> list[object]:
        return [func(self) for func in self.selector.values()]

    @overload
    def __getitem__(self, key: str) -> Any: ...
    @overload
    def __getitem__(self, key: int) -> App: ...
    @overload
    def __getitem__(self, key: slice) -> Apps: ...
    def __getitem__(self, key: str | int | slice):
        if isinstance(key, str):
            return self.groupings[key] if key in self.group_keys else self.selector[key](self)
        if isinstance(key, slice):
            return self.with_iterable(self.i[key])
        return self.i[key]

    def limit(self, limit: int) -> Apps:
        return self[:limit]

    def where(self, __func: Callable[[App], bool]) -> Apps:
        func = App.wrap_open_app(__func)
        return self.with_iterable(self.i.filter(func))

    def select(self, selector: dict[str, Callable[[App], object]]) -> Apps:
        func = App.wrap_with_data(App.wrap_open_app(lambda app: {key: func(app) for (key, func) in selector.items()}))
        return self.with_iterable(self.i.map(func))

    def order_by(self, __func: Callable[[App], SupportsRichComparison], reverse=False) -> Apps:
        func = App.wrap_open_app(__func)
        return self.with_iterable(self.i.sort(func, reverse))

    def group_by(self, grouper: dict[str, Callable[[App], SupportsRichComparison]]) -> GroupedApps:
        key_func = App.wrap_open_app(lambda app: tuple([(key, func(app)) for (key, func) in grouper.items()]))
        map_func = lambda columns, apps: Apps(apps, dict(columns), self.selector)
        return GroupedApps(self.i.group_by(key_func, map_func))

    T = TypeVar("T")

    def map_reduce[T](self, __map_func: Callable[[App], T], reduce_func: Callable[[T, T], T]) -> T | None:
        map_func = App.wrap_open_app(__map_func)
        return self.i.map(map_func).reduce(reduce_func)


class GroupedApps(IterController[Apps]):
    def __init__(self, groups: IterContainer[Apps]):
        super().__init__(groups)

    def with_iterable(self, iterable):
        return GroupedApps(iterable)

    def __get_chart_labels(self, X: str | tuple[str] | None) -> list[str]:
        if self.length == 0:
            return []

        if type(X) == str:
            return [str(group[X]) for group in self.list]

        columns: list[tuple[str, ...]]
        if type(X) == tuple:
            columns = [tuple(str(group[x]) for x in X) for group in self.list]
        else:
            columns = [
                tuple([str(value) for value in group.group_values] + [str(value) for value in group.data_values])
                for group in self.list
            ]

        return list(map(lambda column: ", ".join(column), columns))

    def __get_chart_values(self, y: str | None) -> ArrayLike:
        if self.length == 0:
            return []

        if y is None:
            return [group.length for group in self.list]

        return [group[y] for group in self.list]

    def pie(self, title: str | None = None, x: str | tuple[str] | None = None, y: str | None = None):
        labels = self.__get_chart_labels(x)
        sizes = self.__get_chart_values(y)
        fig, ax = setup_plot(title)
        ax.pie(sizes, labels=labels)
        fig.show()

    def bar(self, title: str | None = None, x: str | tuple[str] | None = None, y: str | None = None):
        labels = self.__get_chart_labels(x)
        heights = self.__get_chart_values(y)
        fig, ax = setup_plot(title)
        ax.bar(labels, height=heights)
        fig.show()

    def table(self):
        if self.length == 0:
            print("Count: 0")
            return

        headers = [*self.list[0].group_keys, *self.list[0].data_keys]
        data = [[*group.group_values, *group.data_values] for group in self.list]
        table = tabulate_html(data, headers=headers)
        display_html(table)
        print(f"Count: {self.length}")

    def __repr__(self):
        if self.length == 0:
            return "Count: 0"

        headers = [*self.list[0].group_keys, *self.list[0].data_keys]
        data = [[*group.group_values, *group.data_values] for group in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

    @overload
    def __getitem__(self, key: int) -> Apps: ...
    @overload
    def __getitem__(self, key: slice) -> GroupedApps: ...
    def __getitem__(self, key: int | slice):
        if isinstance(key, slice):
            return self.with_iterable(self.i[key])
        return self.i[key]

    def limit(self, limit: int) -> GroupedApps:
        return self[:limit]

    def where(self, func: Callable[[Apps], bool]) -> GroupedApps:
        return self.with_iterable(self.i.filter(func))

    def order_by(self, func: Callable[[Apps], SupportsRichComparison], reverse=False) -> GroupedApps:
        return self.with_iterable(self.i.sort(func, reverse))

    def select(self, selector: dict[str, Callable[[Apps], object]]) -> GroupedApps:
        func = Apps.wrap_with_selector(selector)
        return self.with_iterable(self.i.map(func))
