{
  description = "A Nixi companion plugin";

  inputs.nixi.url = "github:olafkfreund/nixoarchy-snowflake";

  outputs =
    { self, nixi }:
    {
      packages = builtins.mapAttrs (
        _: l: {
          default = l.mkCompanionPlugin {
            pname = "my-plugin";
            src = self;
          };
        }
      ) nixi.lib;
    };
}
