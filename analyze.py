from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from numpy.typing import ArrayLike

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import cached_property
from io import BufferedReader
from pathlib import Path
from typing import Callable, TypeVar, cast
from zipfile import ZipFile

from IPython.display import display_html
from tabulate import tabulate

from package import (
    Component,
    Environment,
    GenericJsonFile,
    IterContainer,
    IterController,
    Layout,
    TextFile,
    Version,
    VersionLock,
    setup_plot,
)


class App:
    def __init__(self, env: Environment, org: str, app: str, app_dir: Path, data: dict[str, object] = {}):
        self.env: Environment = env
        self.org = org
        self.app = app
        self.__app_dir = app_dir
        self.data = data

    @property
    def key(self):
        return f"{self.env}-{self.org}-{self.app}"

    @property
    def file_name(self):
        return f"{self.key}.zip"

    @property
    def file_path(self):
        return self.__app_dir.joinpath(self.file_name)

    def __repr__(self):
        headers = ["Env", "Org", "App", *self.data_keys]
        data = [[self.env, self.org, self.app, *self.data_values]]
        return tabulate(data, headers=headers, tablefmt="simple_grid")

    def with_data(self, data: dict[str, object]) -> App:
        if self.open:
            raise Exception("Attempted to copy an `App` object while open for reading, this could cause weird issues!")
        copy = deepcopy(self)
        copy.data = data
        return copy

    @cached_property
    def data_keys(self) -> list[str]:
        return list(self.data.keys())

    @cached_property
    def data_values(self) -> list[object]:
        return list(self.data.values())

    T = TypeVar("T")

    # Uses a context manager to make sure any file operations are closed
    # Does not open any files yet, this happens lazily only when needed
    @staticmethod
    def wrap_open_app(__func: Callable[[App], T]) -> Callable[[App], T]:
        def func(app: App):
            with app as open_app:
                return __func(open_app)

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

    def first_file(self, file_pattern):
        file_names = list(filter(lambda name: re.search(file_pattern, name) is not None, self.files))
        if len(file_names) > 0:
            with self.content.open(file_names[0]) as zf:
                return zf.read(), file_names[0]
        return None, None

    @cached_property
    def application_metadata(self):
        file_data, file_path = self.first_file(r"/App/config/applicationmetadata.json$")
        return GenericJsonFile.from_bytes(file_data, file_path)

    @cached_property
    def layout_sets(self):
        file_data, file_path = self.first_file(r"/App/ui/layout-sets.json$")
        return GenericJsonFile.from_bytes(file_data, file_path)

    @cached_property
    def layout_files(self) -> list[str]:
        return list(filter(lambda name: re.search(r"/App/ui/(FormLayout\.json$|([^/]+/)?layouts/.+\.json$)", name), self.files))

    def generate_layouts(self):
        for layout_file in self.layout_files:
            with self.content.open(layout_file) as zf:
                layout_data = zf.read()
            layout = Layout.from_bytes(layout_data, layout_file)
            if layout.exists:
                yield layout

    @property
    def layouts(self) -> IterContainer[Layout]:
        return IterContainer(self.generate_layouts())

    @property
    def components(self) -> IterContainer[Component]:
        return IterContainer(component for layout in self.generate_layouts() for component in layout.components.list)

    def generate_json_files(self, files: Iterable[str]):
        for file in files:
            with self.content.open(file) as zf:
                data = zf.read()
            json_file = GenericJsonFile.from_bytes(data, file)
            if json_file.exists:
                yield json_file

    @cached_property
    def layout_settings_files(self) -> list[str]:
        return list(filter(lambda name: re.search(r"/App/ui/([^/]+/)?Settings.json$", name), self.files))

    @property
    def layout_settings(self) -> IterContainer[GenericJsonFile]:
        return IterContainer(self.generate_json_files(self.layout_settings_files))

    def generate_text_files(self, files: Iterable[str]):
        for file in files:
            with self.content.open(file) as zf:
                data = zf.read()
            text_file = TextFile.from_bytes(data, file)
            if text_file.exists:
                yield text_file

    @cached_property
    def cs_files(self) -> list[str]:
        return list(filter(lambda name: re.search(r"/App/.*\.cs$", name), self.files))

    @property
    def cs(self) -> IterContainer[TextFile]:
        return IterContainer(self.generate_text_files(self.cs_files))

    @property
    def program_cs(self):
        file_data, file_path = self.first_file(r"/App/Program.cs$")
        return TextFile.from_bytes(file_data, file_path)

    def first_line_match(self, file_pattern: str, line_pattern: str, match_group: int | None) -> str | None:
        file_names = filter(lambda name: re.search(file_pattern, name) is not None, self.files)
        for name in file_names:
            with self.content.open(name) as zf:
                for line in zf.readlines():
                    match = re.search(line_pattern, line.decode())
                    if match is not None:
                        if match_group is not None:
                            return match.group(match_group)
                        return match.group(0)

    @cached_property
    def frontend_version(self) -> Version:
        match = self.first_line_match(
            r"/App/views/Home/Index.cshtml$",
            r'src="https://altinncdn.no/toolkits/altinn-app-frontend/([a-zA-Z0-9\-.]+)/altinn-app-frontend.js"',
            1,
        )
        return Version(match)

    @cached_property
    def backend_version(self) -> Version:
        match = self.first_line_match(
            r"/App/[^/]+.csproj$", r'(?i)Include="Altinn\.App\.(Core|Api|Common)(\.Experimental)?"\s*Version="([a-zA-Z0-9\-.]+)"', 3
        )
        return Version(match)


class Apps(IterController[App]):
    def __init__(self, apps: IterContainer[App], groupings: dict[str, object] = {}, selector: dict[str, Callable[[Apps], object]] = {}):
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
        table = tabulate(data, headers=headers, tablefmt="html")
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
    def init(cls, apps_dir: Path, max_open_files=100) -> Apps:
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
            return (
                [str(group.groupings[X]) for group in self.list]
                if X in self.list[0].group_keys
                else [str(group.data_values[group.data_keys.index(X)]) for group in self.list]
            )
        columns: list[tuple[str, ...]]
        if type(X) == tuple:
            columns = [
                tuple(
                    str(group.groupings[x]) if x in self.list[0].group_keys else str(group.data_values[group.data_keys.index(x)]) for x in X
                )
                for group in self.list
            ]
        else:
            columns = [
                tuple([*(str(value) for value in group.group_values), *(str(value) for value in group.data_values)]) for group in self.list
            ]

        return list(map(lambda column: ", ".join(column), columns))

    def __get_chart_values(self, y: str | None) -> ArrayLike:
        if self.length == 0:
            return []

        if y is None:
            return [group.length for group in self.list]

        return cast(
            ArrayLike,
            (
                [group.groupings[y] for group in self.list]
                if y in self.list[0].group_keys
                else [group.data_values[group.data_keys.index(y)] for group in self.list]
            ),
        )

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
        table = tabulate(data, headers=headers, tablefmt="html")
        display_html(table)
        print(f"Count: {self.length}")

    def __repr__(self):
        if self.length == 0:
            return "Count: 0"

        headers = [*self.list[0].group_keys, *self.list[0].data_keys]
        data = [[*group.group_values, *group.data_values] for group in self.list]
        table = tabulate(data, headers=headers, tablefmt="simple_grid")

        return f"{table}\nCount: {self.length}"

    def limit(self, limit: int) -> GroupedApps:
        return self[:limit]

    def where(self, func: Callable[[Apps], bool]) -> GroupedApps:
        return self.with_iterable(self.i.filter(func))

    def order_by(self, func: Callable[[Apps], SupportsRichComparison], reverse=False) -> GroupedApps:
        return self.with_iterable(self.i.sort(func, reverse))

    def select(self, selector: dict[str, Callable[[Apps], object]]) -> GroupedApps:
        func = Apps.wrap_with_selector(selector)
        return self.with_iterable(self.i.map(func))


def main():
    apps_dir = Path("./data")

    with Apps.init(apps_dir, max_open_files=100) as apps:

        start = time.time()

        # print(
        #     apps.where(
        #         lambda app: app.env == "prod"
        #         and app.frontend_version >= "4.0.0"
        #         and app.frontend_version != "4"
        #         and app.frontend_version.preview is None
        #     )
        #     .select({"Version": lambda app: app.frontend_version})
        #     .order_by(lambda app: app.frontend_version)
        # )

        # apps_v4 = apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version.preview is None)
        # apps_locked = apps_v4.where(lambda app: app.frontend_version != "4")
        # print(f"{apps_locked.length} / {apps_v4.length}")

        # Apps testing navigation feature
        # print(apps.where(lambda app: ".navigation." in app.frontend_version).select({"Frontend version": lambda app: app.frontend_version}))

        # Apps on different major versions frontend
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.exists)
        #     .group_by({"Frontend major version": lambda app: cast(int, app.frontend_version.major)})
        #     .select({"Count": lambda apps: apps.length})
        #     .order_by(lambda apps: (apps.groupings["Frontend major version"],))
        # )

        # Apps on different major versions backend
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.backend_version.exists)
        #     .group_by({"Backend major version": lambda app: app.backend_version.major})
        #     .select({"Count": lambda apps: apps.length})
        #     .order_by(lambda apps: (apps.groupings["Backend major version"],))
        # )

        # Apps in prod not running latest in v4
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
        #     .select({"Frontend version": lambda app: app.frontend_version})
        #     .order_by(lambda app: (app.org, app.frontend_version, app.app))
        # )

        # Service owners with locked app frontend per version
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 4 and app.frontend_version != "4")
        #     .group_by({"Env": lambda app: app.env, "Org": lambda app: app.org, "Frontend version": lambda app: app.frontend_version})
        #     .select(
        #         {
        #             "Count": lambda apps: apps.length,
        #             "Name": lambda apps: apps.map_reduce(lambda app: app.app, lambda a, b: min(a, b)),
        #         }
        #     )
        #     .order_by(lambda apps: (apps.groupings["Org"], apps.groupings["Frontend version"]))
        # )

        # Backend frontend pairs in v4/v8
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.backend_version.major == 8 and app.frontend_version.major == 4)
        #     .group_by({"Backend version": lambda app: app.backend_version, "Frontend version": lambda app: app.frontend_version})
        #     .order_by(lambda apps: (apps.length), reverse=True)
        #     .select({"Count": lambda apps: apps.length})
        # )

        # Backend v8 version usage
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.backend_version == "8.0.0")
        #     .group_by({"Env": lambda app: app.env, "Org": lambda app: app.org, "Backend version": lambda app: app.backend_version})
        #     .order_by(lambda apps: (apps.length, apps.groupings["Backend version"]), reverse=True)
        #     .select({"Count": lambda apps: apps.length})
        # )

        # Number of layout files
        # print(
        #     apps.where(lambda app: len(app.layout_files) > 0)
        #     .select({"Number of layout files": lambda app: len(app.layout_files)})
        #     .order_by(lambda app: len(app.layout_files), reverse=True)
        # )

        # Apps with Custom component
        # print(
        #     apps.where(lambda app: app.components.some(lambda component: component.type == "Custom"))
        #     .select({"Custom components": lambda app: app.components.filter(lambda component: component.type == "Custom").length})
        #     .order_by(lambda app: app.components.filter(lambda component: component.type == "Custom").length, reverse=True)
        # )

        # Unique custom components
        # print(
        #     apps.where(lambda app: app.components.some(lambda component: component.type == "Custom"))
        #     .select(
        #         {
        #             "Unique custom components": lambda app: app.components.filter(lambda component: component.type == "Custom")
        #             .map(lambda component: component.jq(".tagName").first)
        #             .filter(lambda tagName: tagName is not None)
        #             .unique()
        #             .length
        #         }
        #     )
        #     .order_by(lambda app: (app.data["Unique custom components"],), reverse=True)
        # )

        # print(apps.where(lambda app: app.frontend_version.major == 2).select({"Frontend version": lambda app: app.frontend_version}))

        # Stateless apps in prod
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.application_metadata[".onEntry.show"] not in [None, 'select-instance', 'new-instance']).select(
        #         {"On entry": lambda app: (app.application_metadata[".onEntry.show"])}
        #     )
        # )

        # Apps using layout sets in v3 (prod)
        # print(apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 3 and app.layout_sets.exists))

        # Apps actually using navigation
        # print(
        #     apps.where(lambda app: app.layout_settings.some(lambda layout_settings: layout_settings[".pages.groups"] != None))
        # )

        # Stateless anonymous apps
        # print(
        #     apps.where(
        #         lambda app: app.env == "prod"
        #         and app.application_metadata[".onEntry.show"] not in [None, "select-instance", "new-instance"]
        #         and app.application_metadata[".dataTypes.[].appLogic.allowAnonymousOnStateless", :].some(lambda value: value == True)
        #     ).select(
        #         {
        #             "On entry": lambda app: (app.application_metadata[".onEntry.show"]),
        #             "Anonymous dataType": lambda app: app.application_metadata[".dataTypes.[]", :]
        #             .filter(lambda dataType: dataType[".appLogic.allowAnonymousOnStateless"] == True)
        #             .map(lambda dataType: dataType[".id"])
        #             .first,
        #         }
        #     )
        # )

        # IFormDataValidators
        # print(
        #     apps.where(lambda app: app.program_cs[r"\.AddTransient<IFormDataValidator,"] != None).select(
        #         {"Validators": lambda app: app.program_cs[r"\.AddTransient<IFormDataValidator,\s*([^>]+)>", 1, :]}
        #     )
        # )

        print()
        print(f"Time: {time.time() - start:.2f}s")


if __name__ == "__main__":
    main()
