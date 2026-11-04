self:
{ config, lib, pkgs, ... }:
let
  cfg = config.services.nixi-status;

  # a tailnet IPv4 address: 100.64.0.0/10, and not the MagicDNS address
  tailnetIp =
    a:
    let
      o = map lib.toInt (lib.splitString "." a);
    in
    builtins.match "[0-9]+(\\.[0-9]+){3}" a != null
    && builtins.all (n: n <= 255) o
    && builtins.elemAt o 0 == 100
    && builtins.elemAt o 1 >= 64
    && builtins.elemAt o 1 <= 127
    && a != "100.100.100.100";
in
{
  options.services.nixi-status = {
    enable = lib.mkEnableOption "the nixi-status read-only host status endpoint on the tailnet";
    address = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "This host's tailnet IPv4 address to bind (100.64.0.0/10).";
    };
    port = lib.mkOption {
      type = lib.types.port;
      default = 9188;
      description = "TCP port; opened on the tailscale interface only.";
    };
    allowedCallers = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Tailnet IPv4 addresses allowed to call the endpoint.";
    };
    tokenFile = lib.mkOption {
      type = lib.types.nullOr (lib.types.pathWith { inStore = false; absolute = true; });  # a store path is world-readable
      default = null;
      description = "Runtime path of the shared token (an agenix path), read through LoadCredential; never a store path.";
    };
    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.nixi-status;
      description = "Package providing bin/nixi-status.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.services.tailscale.enable;
        message = "services.nixi-status requires services.tailscale.enable";
      }
      {
        assertion = cfg.address != null;
        message = "services.nixi-status.address must be set";
      }
      {
        assertion = cfg.tokenFile != null;
        message = "services.nixi-status.tokenFile must be set";
      }
      {
        assertion = cfg.allowedCallers != [ ];
        message = "services.nixi-status.allowedCallers must not be empty";
      }
      {
        assertion = builtins.all tailnetIp cfg.allowedCallers;
        message = "services.nixi-status.allowedCallers entries must be IPv4 in 100.64.0.0/10 and not 100.100.100.100";
      }
      {
        assertion = cfg.address == null || tailnetIp cfg.address;
        message = "services.nixi-status.address must be IPv4 in 100.64.0.0/10 and not 100.100.100.100";
      }
    ];

    systemd.services.nixi-status = {
      wantedBy = [ "multi-user.target" ];
      after = [ "tailscaled.service" ];
      wants = [ "tailscaled.service" ];
      path = [ pkgs.systemd ];
      serviceConfig = {
        ExecStart =
          "${cfg.package}/bin/nixi-status --address ${lib.escapeShellArg (toString cfg.address)} --port ${toString cfg.port} "
          + lib.concatMapStrings (a: "--allow ${lib.escapeShellArg a} ") cfg.allowedCallers
          + "--token-file %d/token";
        LoadCredential = "token:${toString cfg.tokenFile}";
        DynamicUser = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
        CapabilityBoundingSet = "";
        RestrictAddressFamilies = [ "AF_INET" "AF_UNIX" ];
        MemoryMax = "64M";
        Restart = "always";
        RestartSec = 5;
      };
    };

    networking.firewall.interfaces.${config.services.tailscale.interfaceName}.allowedTCPPorts = [ cfg.port ];
  };
}
