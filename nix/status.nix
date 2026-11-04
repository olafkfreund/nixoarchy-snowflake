# nixi-status alone (#168): the read-only answering service, without the
# companion's GTK, WebKit and Whisper (a 2.6 GiB closure a server doesn't need).
# status_serve.py needs only plugins.py's system_status(), which is stdlib.
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  systemd,
}:
stdenvNoCC.mkDerivation {
  pname = "nixi-status";
  version = "0.1.0";
  src = lib.fileset.toSource {
    root = ../app;
    fileset = lib.fileset.unions [ ../app/status_serve.py ../app/plugins.py ];
  };
  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    mkdir -p $out/share/nixi-status $out/bin
    cp status_serve.py plugins.py $out/share/nixi-status/
    makeWrapper ${python3}/bin/python3 $out/bin/nixi-status \
      --add-flags $out/share/nixi-status/status_serve.py \
      --prefix PATH : ${lib.makeBinPath [ systemd ]}
  '';
  meta.mainProgram = "nixi-status";
}
