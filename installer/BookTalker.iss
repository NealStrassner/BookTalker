; BookTalker installer (Inno Setup 6). Build: ISCC.exe installer\BookTalker.iss  ->  installer\Output\BookTalker-Setup-<ver>.exe
; Installs into Program Files for everyone (asks for administrator once); the first screen also
; offers "only for me", which needs no administrator and installs into %LOCALAPPDATA%\Programs.

#define AppName "BookTalker"
#define AppVersion "1.0.3"
#define AppExe "BookTalker.exe"

[Setup]
AppId={{6F2B1C9E-4D7A-4B3E-9A51-B00C7A1C0DE1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Neal Strassner
AppCopyright=Copyright (C) 2026 Neal Strassner
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=BookTalker-Setup-{#AppVersion}
SetupIconFile=..\booktalker.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
WizardSizePercent=120
; the welcome page carries the dedication (photo + one line, [Code] below)
DisableWelcomePage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "nl"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "he"; MessagesFile: "compiler:Languages\Hebrew.isl"
Name: "ar"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "cs"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "sv"; MessagesFile: "compiler:Languages\Swedish.isl"
Name: "da"; MessagesFile: "compiler:Languages\Danish.isl"
Name: "no"; MessagesFile: "compiler:Languages\Norwegian.isl"
Name: "fi"; MessagesFile: "compiler:Languages\Finnish.isl"
Name: "hu"; MessagesFile: "compiler:Languages\Hungarian.isl"
Name: "th"; MessagesFile: "compiler:Languages\Thai.isl"
Name: "ta"; MessagesFile: "compiler:Languages\Tamil.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "openwith"; Description: "Add BookTalker to ""Open with"" for books and documents"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\BookTalker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; the dedication photo, one size per display scaling (only shown, never installed; kept out of
; the public source, so a build without it simply shows no photo)
Source: "dedication\photo_*.bmp"; Flags: dontcopy skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; "Open with" only (never takes over a file type the user already opens with something else)
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".epub"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".mobi"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".azw3"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".fb2"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".djvu"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".cbz"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".cbr"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".docx"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".txt"; ValueData: ""; Tasks: openwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; files that came later through About -> Check for updates (the uninstaller only knows its own)
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#AppExe}"

; The reader's settings, bookmarks, voices and downloaded packs live in %LOCALAPPDATA%\BookTalker
; and are kept on uninstall (installing again picks them up).

[Code]
// Welcome page: the photo of Grandpa Felix reading to his grandchildren, centred under the
// welcome text, with the dedication beneath it.
procedure InitializeWizard;
var
  Page: TNewNotebookPage;
  Photo: TBitmapImage;
  Line: TNewStaticText;
  Sizes: array of Integer;
  I, W, H, Top, Margin, Pick: Integer;
begin
  Page := WizardForm.WelcomePage;
  Margin := ScaleX(24);
  WizardForm.WizardBitmapImage.Visible := False;
  WizardForm.WelcomeLabel1.Left := Margin;
  WizardForm.WelcomeLabel1.Width := Page.Width - 2 * Margin;
  WizardForm.WelcomeLabel1.Top := ScaleY(14);
  WizardForm.WelcomeLabel1.AdjustHeight;
  WizardForm.WelcomeLabel2.Left := Margin;
  WizardForm.WelcomeLabel2.Width := Page.Width - 2 * Margin;
  WizardForm.WelcomeLabel2.Top := WizardForm.WelcomeLabel1.Top + WizardForm.WelcomeLabel1.Height + ScaleY(6);
  WizardForm.WelcomeLabel2.AdjustHeight;

  Top := WizardForm.WelcomeLabel2.Top + WizardForm.WelcomeLabel2.Height + ScaleY(10);
  H := Page.Height - Top - ScaleY(34);                 // room left for the photo and its line
  W := H * 1735 div 1080;
  if W > Page.Width - 2 * Margin then
  begin
    W := Page.Width - 2 * Margin;
    H := W * 1080 div 1735;
  end;

  // the smallest prepared size that is at least as wide as the space (sharp at any scaling)
  Sizes := [420, 525, 630, 840, 1050];
  Pick := Sizes[GetArrayLength(Sizes) - 1];
  for I := GetArrayLength(Sizes) - 1 downto 0 do
    if Sizes[I] >= W then
      Pick := Sizes[I];
  try
    ExtractTemporaryFile('photo_' + IntToStr(Pick) + '.bmp');
  except
    exit;                                              // (a build without the photo: no dedication)
  end;

  Photo := TBitmapImage.Create(WizardForm);
  Photo.Parent := Page;
  Photo.Bitmap.LoadFromFile(ExpandConstant('{tmp}\photo_' + IntToStr(Pick) + '.bmp'));
  Photo.Stretch := True;
  Photo.SetBounds((Page.Width - W) div 2, Top, W, H);

  Line := TNewStaticText.Create(WizardForm);
  Line.Parent := Page;
  Line.Caption := 'Dedicated to my grandpa Felix ' + #$2014 + ' the original BookTalker';
  Line.Font.Style := [fsItalic];
  Line.Font.Size := WizardForm.WelcomeLabel2.Font.Size + 1;
  Line.Top := Top + H + ScaleY(8);
  Line.Left := (Page.Width - Line.Width) div 2;
end;
