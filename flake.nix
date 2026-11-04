{
  description = "Nixi desktop companion";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs, ... }:
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
          nixi-status = pkgs.callPackage ./nix/status.nix { };
        in
        {
          inherit nixi-companion nixi-status;
          default = nixi-companion;
        }
      );

      nixosModules.status = import ./nix/status-module.nix self;

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

          # a minimal host with the status module; extra = module attrs merged over the valid values
          host =
            extra:
            nixpkgs.lib.nixosSystem {
              system = "x86_64-linux";
              modules = [
                self.nixosModules.status
                {
                  services.tailscale.enable = true;
                  services.nixi-status = {
                    enable = true;
                    address = "100.118.96.32";
                    allowedCallers = [ "100.69.100.115" ];
                    tokenFile = "/run/agenix/nixi-status-token";
                  };
                  fileSystems."/" = {
                    device = "none";
                    fsType = "tmpfs";
                  };
                  boot.loader.grub.enable = false;
                  system.stateVersion = "25.05";
                }
                extra
              ];
            };
          failed = c: map (a: a.message) (builtins.filter (a: !a.assertion) c.config.assertions);
          good = host { };
          fw = good.config.networking.firewall;
          # (name, module override, expected failing message fragment)
          bad = {
            no-address = [ { services.nixi-status.address = nixpkgs.lib.mkForce null; } "address must be set" ];
            no-token = [ { services.nixi-status.tokenFile = nixpkgs.lib.mkForce null; } "tokenFile must be set" ];
            no-callers = [ { services.nixi-status.allowedCallers = nixpkgs.lib.mkForce [ ]; } "must not be empty" ];
            lan-caller = [ { services.nixi-status.allowedCallers = nixpkgs.lib.mkForce [ "192.168.1.65" ]; } "allowedCallers entries must be" ];
            magicdns-caller = [ { services.nixi-status.allowedCallers = nixpkgs.lib.mkForce [ "100.100.100.100" ]; } "allowedCallers entries must be" ];
            no-tailscale = [ { services.tailscale.enable = nixpkgs.lib.mkForce false; } "requires services.tailscale.enable" ];
          };
          badOk = nixpkgs.lib.all (
            n:
            let
              r = builtins.elemAt bad.${n} 0;
              want = builtins.elemAt bad.${n} 1;
              msgs = failed (host r);
            in
            builtins.length msgs == 1 && nixpkgs.lib.hasInfix want (builtins.head msgs)
          ) (builtins.attrNames bad);
        in
        {
          # a deliberately broken manifest must fail the build, and say why
          broken-manifest-fails = pkgs.runCommand "broken-manifest-fails" { } ''
            grep -q "unknown key: surprise" ${broken}/testBuildFailure.log
            touch $out
          '';

          status-module =
            assert failed good == [ ];
            assert fw.interfaces.tailscale0.allowedTCPPorts == [ 9188 ];
            assert !(builtins.elem 9188 fw.allowedTCPPorts);
            pkgs.writeText "nixi-status.service" good.config.systemd.units."nixi-status.service".text;

          status-module-assertions =
            assert badOk;
            pkgs.runCommand "status-module-assertions" { } "touch $out";
        }
      );

      formatter = forSystems (system: nixpkgs.legacyPackages.${system}.nixpkgs-fmt);
    };
}
