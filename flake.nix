{
  description = "Nixi desktop companion";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          nixi-companion = pkgs.callPackage ./nix/package.nix { };
        in
        {
          inherit nixi-companion;
          default = nixi-companion;
        }
      );

      # lib.<system>.mkCompanionPlugin { src, pname }: a plugin folder whose manifest is checked at build time (#149)
      lib = forSystems (system: {
        mkCompanionPlugin = nixpkgs.legacyPackages.${system}.callPackage ./nix/plugin.nix { };
      });

      # nix build .#examples.party-hat-plus: every folder in plugins/examples/
      legacyPackages = forSystems (
        system:
        let
          mk = nixpkgs.legacyPackages.${system}.callPackage ./nix/plugin.nix { };
          dir = ./plugins/examples;
        in
        {
          examples = nixpkgs.lib.mapAttrs (name: _: mk {
            pname = name;
            src = dir + "/${name}";
          }) (nixpkgs.lib.filterAttrs (_: t: t == "directory") (builtins.readDir dir));
        }
      );

      checks = forSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          mk = pkgs.callPackage ./nix/plugin.nix { };
          broken = pkgs.testers.testBuildFailure (mk {
            pname = "broken-plugin";
            src = ./tests/fixtures/plugins/broken;
          });
        in
        {
          # a deliberately broken manifest must fail the build, and say why
          broken-manifest-fails = pkgs.runCommand "broken-manifest-fails" { } ''
            grep -q "unknown key: surprise" ${broken}/testBuildFailure.log
            touch $out
          '';
        }
      );

      formatter = forSystems (system: nixpkgs.legacyPackages.${system}.nixpkgs-fmt);
    };
}
