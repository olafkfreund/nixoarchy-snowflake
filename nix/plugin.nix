# lib.mkCompanionPlugin { src, pname }: a companion plugin folder (#149), checked when it is built.
# A bad plugin.json (or prop.svg) fails the build instead of showing up broken in Settings.
{ stdenvNoCC, python3 }:
{ src, pname }:
stdenvNoCC.mkDerivation {
  inherit pname src;
  version = "0";
  dontConfigure = true;
  dontBuild = true;
  doCheck = true;
  nativeCheckInputs = [ python3 ];
  checkPhase = ''
    python3 ${../app/plugins.py} --check .
  '';
  installPhase = ''
    runHook preInstall
    cp -r . $out
    runHook postInstall
  '';
}
