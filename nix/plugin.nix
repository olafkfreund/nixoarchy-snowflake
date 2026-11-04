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
    # plugins.py imports stages.py (the phrases Nixi keeps for itself), and so does quick.py, so both are copied next to each other
    mkdir -p $TMPDIR/checker
    cp ${../app/plugins.py} $TMPDIR/checker/plugins.py
    cp ${../app/stages.py} $TMPDIR/checker/stages.py
    cp ${../app/quick.py} $TMPDIR/checker/quick.py
    cp -r ${../app/lang} $TMPDIR/checker/lang
    python3 $TMPDIR/checker/plugins.py --check .
  '';
  installPhase = ''
    runHook preInstall
    cp -r . $out
    runHook postInstall
  '';
}
