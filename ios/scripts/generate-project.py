#!/usr/bin/env python3
"""Generate the dependency-free Xcode project for the 17同游 iOS shell. Safe to rerun after adding Swift files."""
from pathlib import Path
import hashlib, json, plistlib
from xml.sax.saxutils import escape
root = Path(__file__).resolve().parent.parent

def uid(name):
    return hashlib.sha256(name.encode()).hexdigest()[:24].upper()

def q(value):
    return json.dumps(str(value))

files = sorted((root/'Tongyou').rglob('*.swift'))
resources = ['Tongyou/Resources/Assets.xcassets']
objects = []

def add(name, body):
    objects.append(f'{uid(name)} = {{ {body} }};')
    return uid(name)

refs, builds, resource_builds = [], [], []
for path in [str(f.relative_to(root)) for f in files] + resources:
    resource = path in resources
    kind = 'folder.assetcatalog' if path.endswith('xcassets') else ('text.xml' if resource else 'sourcecode.swift')
    ref = add('file:'+path, f'isa = PBXFileReference; lastKnownFileType = {kind}; path = {q(path)}; sourceTree = SOURCE_ROOT;')
    build = add('build:'+path, f'isa = PBXBuildFile; fileRef = {ref};')
    refs.append(ref)
    (resource_builds if resource else builds).append(build)
product = add('product', 'isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = Tongyou.app; sourceTree = BUILT_PRODUCTS_DIR;')
add('products', f'isa = PBXGroup; children = ({product},{uid("uiProduct")},); name = Products; sourceTree = "<group>";')
add('sources', f'isa = PBXGroup; children = ({",".join(refs)},); name = Tongyou; sourceTree = "<group>";')
add('root', f'isa = PBXGroup; children = ({uid("sources")},{uid("products")},); sourceTree = "<group>";')
add('sourcesPhase', f'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ({",".join(builds)},); runOnlyForDeploymentPostprocessing = 0;')
add('resourcesPhase', f'isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ({",".join(resource_builds)},); runOnlyForDeploymentPostprocessing = 0;')
add('frameworksPhase', 'isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
for scope in ['project', 'target']:
    for config in ['Debug','Release']:
        settings = {
            'SDKROOT': 'iphoneos', 'IPHONEOS_DEPLOYMENT_TARGET': '26.0',
            'CLANG_ENABLE_MODULES': 'YES', 'SWIFT_VERSION': '5.0',
        }
        if scope == 'target':
            settings.update({
                'PRODUCT_BUNDLE_IDENTIFIER':'com.yuchengjiang.tongyou', 'PRODUCT_NAME':'$(TARGET_NAME)',
                'INFOPLIST_FILE':'Tongyou/Resources/Info.plist', 'GENERATE_INFOPLIST_FILE':'NO',
                'CODE_SIGN_STYLE':'Automatic', 'DEVELOPMENT_TEAM':'9F8GSH96PT', 'TARGETED_DEVICE_FAMILY':'1',
                'SUPPORTED_PLATFORMS':'iphoneos iphonesimulator', 'SUPPORTS_MACCATALYST':'NO',
                'SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD':'NO',
                'ASSETCATALOG_COMPILER_APPICON_NAME':'AppIcon',
                'ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME':'AccentColor',
                'MARKETING_VERSION':'1.0.7', 'CURRENT_PROJECT_VERSION':'8',
                'LD_RUNPATH_SEARCH_PATHS':'$(inherited) @executable_path/Frameworks',
                'SWIFT_STRICT_CONCURRENCY':'minimal', 'ENABLE_PREVIEWS':'YES',
            })
        if config == 'Debug':
            settings.update({'SWIFT_OPTIMIZATION_LEVEL':'-Onone', 'SWIFT_ACTIVE_COMPILATION_CONDITIONS':'DEBUG $(inherited)', 'DEBUG_INFORMATION_FORMAT':'dwarf', 'ENABLE_TESTABILITY':'YES'})
        else:
            settings.update({'SWIFT_OPTIMIZATION_LEVEL':'-O', 'SWIFT_COMPILATION_MODE':'wholemodule', 'DEBUG_INFORMATION_FORMAT':'dwarf-with-dsym'})
        body = ' '.join(f'{k} = {q(v)};' for k,v in settings.items())
        add(scope+config, f'isa = XCBuildConfiguration; buildSettings = {{ {body} }}; name = {config};')
    add(scope+'Configs', f'isa = XCConfigurationList; buildConfigurations = ({uid(scope+"Debug")},{uid(scope+"Release")},); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
add('target', f'isa = PBXNativeTarget; buildConfigurationList = {uid("targetConfigs")}; buildPhases = ({uid("sourcesPhase")},{uid("frameworksPhase")},{uid("resourcesPhase")},); buildRules = (); dependencies = (); name = Tongyou; productName = Tongyou; productReference = {product}; productType = "com.apple.product-type.application";')
add('project', f'isa = PBXProject; attributes = {{ BuildIndependentTargetsInParallel = YES; LastUpgradeCheck = 1500; TargetAttributes = {{ {uid("target")} = {{ CreatedOnToolsVersion = 15.0; }}; }}; }}; buildConfigurationList = {uid("projectConfigs")}; compatibilityVersion = "Xcode 14.0"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en, Base, "zh-Hans",); mainGroup = {uid("root")}; productRefGroup = {uid("products")}; projectDirPath = ""; projectRoot = ""; targets = ({uid("target")},{uid("uiTarget")},);')
# UI tests are a separate bundle, never included in the shipped application.
add('uiFile', 'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "UITests/LedgerLinkUITests.swift"; sourceTree = SOURCE_ROOT;')
add('uiBuild', f'isa = PBXBuildFile; fileRef = {uid("uiFile")};')
add('uiProduct', 'isa = PBXFileReference; explicitFileType = wrapper.cfbundle; path = TongyouUITests.xctest; sourceTree = BUILT_PRODUCTS_DIR;')
add('uiPhase', f'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ({uid("uiBuild")},); runOnlyForDeploymentPostprocessing = 0;')
add('uiFrameworks', 'isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
add('uiProxy', f'isa = PBXContainerItemProxy; containerPortal = {uid("project")}; proxyType = 1; remoteGlobalIDString = {uid("target")}; remoteInfo = Tongyou;')
add('uiDependency', f'isa = PBXTargetDependency; target = {uid("target")}; targetProxy = {uid("uiProxy")};')
for config in ['Debug', 'Release']:
    settings = {'SDKROOT':'iphoneos', 'IPHONEOS_DEPLOYMENT_TARGET':'26.0', 'SWIFT_VERSION':'5.0',
                'PRODUCT_BUNDLE_IDENTIFIER':'com.yuchengjiang.tongyou.uitests', 'PRODUCT_NAME':'$(TARGET_NAME)',
                'GENERATE_INFOPLIST_FILE':'YES', 'TEST_TARGET_NAME':'Tongyou', 'TARGETED_DEVICE_FAMILY':'1',
                'CODE_SIGN_STYLE':'Automatic', 'DEVELOPMENT_TEAM':'9F8GSH96PT',
                'LD_RUNPATH_SEARCH_PATHS':'$(inherited) @executable_path/Frameworks @loader_path/Frameworks'}
    add('ui'+config, 'isa = XCBuildConfiguration; buildSettings = { '+ ' '.join(f'{k} = {q(v)};' for k,v in settings.items()) +f' }}; name = {config};')
add('uiConfigs', f'isa = XCConfigurationList; buildConfigurations = ({uid("uiDebug")},{uid("uiRelease")},); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
add('uiTarget', f'isa = PBXNativeTarget; buildConfigurationList = {uid("uiConfigs")}; buildPhases = ({uid("uiPhase")},{uid("uiFrameworks")},); buildRules = (); dependencies = ({uid("uiDependency")},); name = TongyouUITests; productName = TongyouUITests; productReference = {uid("uiProduct")}; productType = "com.apple.product-type.bundle.ui-testing";')
project_dir = root/'Tongyou.xcodeproj'
project_dir.mkdir(exist_ok=True)
(project_dir/'project.pbxproj').write_text('// !$*UTF8*$!\n{ archiveVersion = 1; classes = {}; objectVersion = 56; objects = {\n'+ '\n'.join(objects) +f'\n}}; rootObject = {uid("project")}; }}\n')
scheme_dir = project_dir/'xcshareddata/xcschemes'
scheme_dir.mkdir(parents=True, exist_ok=True)
ref = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{uid("target")}" BuildableName="Tongyou.app" BlueprintName="Tongyou" ReferencedContainer="container:Tongyou.xcodeproj"/>'
scheme = f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1500" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{ref}</BuildActionEntry></BuildActionEntries></BuildAction>
<TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES"><Testables><TestableReference skipped="NO"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{uid('uiTarget')}" BuildableName="TongyouUITests.xctest" BlueprintName="TongyouUITests" ReferencedContainer="container:Tongyou.xcodeproj"/></TestableReference></Testables></TestAction>
<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></LaunchAction>
<ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></ProfileAction>
<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
'''
(scheme_dir/'Tongyou.xcscheme').write_text(scheme)
print(f'Generated {len(files)} Swift sources and {len(resources)} resources in {project_dir}')
