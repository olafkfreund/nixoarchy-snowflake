{
  lib,
  stdenvNoCC,
  makeWrapper,
  wrapGAppsHook3,
  gobject-introspection,
  gtk3,
  webkitgtk_4_1,
  gtk-layer-shell,
  glib-networking,
  gst_all_1,
  python3,
  grim,
  slurp,
  wl-clipboard,
  libnotify,
  playerctl,
  pulseaudio,
  brightnessctl,
  piper-tts,
  espeak-ng,
  procps,
  wireplumber,
  pipewire,
  alsa-utils,
  nixiBridge ? null,
}:
let
  # speaking only: no Japanese (its pyopenjtalk-plus fails its tests on current unstable) and no training extras
  piper = piper-tts.override {
    withJapanese = false;
    withTrain = false;
  };
  py = python3.withPackages (p: [
    p.pygobject3
    p.pycairo
    p.numpy
    p.pillow
    p.faster-whisper
  ]);
in
stdenvNoCC.mkDerivation {
  pname = "nixi-companion";
  version = "0.1.0";
  src = ../.;

  nativeBuildInputs = [
    makeWrapper
    wrapGAppsHook3
    gobject-introspection
  ];
  buildInputs = [
    gtk3
    webkitgtk_4_1
    gtk-layer-shell
    glib-networking
    gst_all_1.gstreamer
    gst_all_1.gst-plugins-base
    gst_all_1.gst-plugins-good
  ];

  dontConfigure = true;
  dontBuild = true;
  dontWrapGApps = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/share/nixi-companion $out/bin $out/share/applications $out/share/icons/hicolor/512x512/apps
    cp -r app $out/share/nixi-companion/app
    install -m755 bin/nixi-companion $out/bin/nixi-companion
    install -m644 data/nixi-companion.desktop $out/share/applications/nixi-companion.desktop
    install -m644 app/static/icon.png $out/share/icons/hicolor/512x512/apps/nixi-companion.png
    ${lib.optionalString (nixiBridge != null) ''
      substituteInPlace $out/share/nixi-companion/app/server.py \
        --replace-fail '"@nixiBridge@"' ${lib.escapeShellArg (builtins.toJSON (builtins.toJSON nixiBridge))}
    ''}
    runHook postInstall
  '';

  # gappsWrapperArgs is only filled in during fixup
  postFixup = ''
    wrapProgram $out/bin/nixi-companion \
      --set NIXI_COMPANION_PYTHON ${py}/bin/python \
      --set NIXI_COMPANION_APP $out/share/nixi-companion/app \
      --prefix PATH : ${
        lib.makeBinPath [
          grim
          slurp
          wl-clipboard
          libnotify
          playerctl
          pulseaudio
          brightnessctl
          piper
          espeak-ng
          procps
          wireplumber
          pipewire
          alsa-utils
        ]
      } \
      "''${gappsWrapperArgs[@]}"
  '';
}
