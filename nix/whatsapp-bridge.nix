# nixi-whatsapp-bridge (#126): the Go linked device the nixi-whatsapp user service runs.
{ lib, buildGoModule }:
buildGoModule {
  pname = "nixi-whatsapp-bridge";
  version = "0.1.0";
  src = lib.fileset.toSource {
    root = ../whatsapp-bridge;
    # sources only, so a local `go build` output never reaches the store
    fileset = lib.fileset.unions [
      ../whatsapp-bridge/go.mod
      ../whatsapp-bridge/go.sum
      (lib.fileset.fileFilter (f: f.hasExt "go") ../whatsapp-bridge)
    ];
  };
  vendorHash = "sha256-RhI73AK6wVvCZub6hGYPZzkqlzLemaRV0AXSvwYvH+4=";
  env.CGO_ENABLED = 1;
  doCheck = true;
  postInstall = ''
    mv $out/bin/whatsapp-client $out/bin/nixi-whatsapp-bridge
  '';
  meta.mainProgram = "nixi-whatsapp-bridge";
}
