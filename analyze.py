from time import time

from package.apps import Apps


def main():
    with Apps.init() as apps:
        start = time()

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
        #             "Unique custom components": lambda app: app.components.filter(
        #                 lambda component: component.type == "Custom"
        #             )
        #             .map(lambda component: component[".tagName"])
        #             .filter(lambda tagName: tagName != None)
        #             .unique()
        #             .length
        #         }
        #     )
        #     .order_by(lambda app: (app.data["Unique custom components"],), reverse=True)
        # )

        # print(
        #     apps.where(lambda app: app.components.some(lambda component: component.type == "Custom"))
        #     .select(
        #         {
        #             "Custom component tags": lambda app: app.components.filter(
        #                 lambda component: component.type == "Custom"
        #             )
        #             .map(lambda component: component[".tagName"])
        #             .unique()
        #             .sort()
        #         }
        #     )
        #     .order_by(lambda app: (app.org, app.app))
        # )

        # print(apps.where(lambda app: app.frontend_version.major == 2).select({"Frontend version": lambda app: app.frontend_version}))

        # Stateless apps in prod
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.application_metadata[".onEntry.show"] not in [None, 'select-instance', 'new-instance']).select(
        #         {"On entry": lambda app: (app.application_metadata[".onEntry.show"])}
        #     )
        # )

        # Apps using layout sets in v3 (prod)
        # print(
        #     apps.where(lambda app: app.env == "prod" and app.frontend_version.major == 3 and app.layout_sets_new.exists)
        # )

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

        # Uses RemoveHiddenData
        # print(
        #     apps.where(
        #         lambda app: app.env == "prod"
        #         and app.app_settings.some(
        #             lambda app_settings: app_settings.environment in ["Production", "default"]
        #             and app_settings[".AppSettings.RemoveHiddenData"] == True
        #         )
        #     )
        # )

        # print(
        #     apps.where(
        #         lambda app: app.frontend_version.exists and app.layouts.is_not_empty and app.layout_settings.is_empty
        #     ).select({"Frontend version": lambda app: app.frontend_version})
        # )

        print()
        print(f"Time: {time() - start:.2f}s")


if __name__ == "__main__":
    main()
