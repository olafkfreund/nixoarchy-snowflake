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

      formatter = forSystems (system: nixpkgs.legacyPackages.${system}.nixpkgs-fmt);
    };
}
