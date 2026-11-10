# Turns a psxrecomp game project's psx-runtime target into a signed iOS app.
# Passed by ps1ios as -DCMAKE_PROJECT_INCLUDE=<repo>/ios/ios.cmake with an iOS
# configure (-G Xcode -DCMAKE_SYSTEM_NAME=iOS). Works for any project made from
# psxrecomp's template (target psx-runtime), including curated ones.
include_guard(GLOBAL)
if(NOT CMAKE_SYSTEM_NAME STREQUAL "iOS")
    return()
endif()
set(PS1IOS_DIR "${CMAKE_CURRENT_LIST_DIR}")
enable_language(OBJCXX)

# Desktop-only features off: TCP debug server, netplay, recomp-ui launcher.
set(PSX_DEBUG_TOOLS OFF CACHE BOOL "" FORCE)
set(PSX_NETPLAY OFF CACHE BOOL "" FORCE)
set(PSX_STATIC_RUNTIME OFF CACHE BOOL "" FORCE)
set(PSX_RECOMP_UI OFF CACHE BOOL "" FORCE)
set(PSX_ENABLE_VULKAN ON CACHE BOOL "" FORCE)   # MoltenVK -> Metal
set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)

set(PS1IOS_BUNDLE_ID "com.example.ps1game" CACHE STRING "iOS bundle identifier")
set(PS1IOS_DISPLAY_NAME "PS1 Game" CACHE STRING "Home screen name")
set(PS1IOS_TEAM "" CACHE STRING "Apple Developer team ID")
set(PS1IOS_GAMEDATA "" CACHE PATH "Folder copied into the app as GameData/ (game.toml, mods, assets)")
set(PS1IOS_MOLTENVK "" CACHE PATH "MoltenVK.xcframework")

function(ps1ios_finalize)
    if(NOT TARGET psx-runtime)
        message(FATAL_ERROR "ps1ios: psx-runtime target not found in this project")
    endif()
    target_sources(psx-runtime PRIVATE "${PS1IOS_DIR}/src/ios_platform.mm")
    target_include_directories(psx-runtime PRIVATE "${PS1IOS_DIR}/src")
    target_link_libraries(psx-runtime PRIVATE
        "-framework UIKit" "-framework GameController" "-framework Metal"
        "-framework QuartzCore" "-framework AVFoundation" "-framework CoreHaptics")
    set_target_properties(psx-runtime PROPERTIES
        OUTPUT_NAME "PS1Game"
        MACOSX_BUNDLE TRUE
        MACOSX_BUNDLE_INFO_PLIST "${PS1IOS_DIR}/Info.plist.in"
        MACOSX_BUNDLE_BUNDLE_NAME "${PS1IOS_DISPLAY_NAME}"
        MACOSX_BUNDLE_GUI_IDENTIFIER "${PS1IOS_BUNDLE_ID}"
        XCODE_ATTRIBUTE_PRODUCT_BUNDLE_IDENTIFIER "${PS1IOS_BUNDLE_ID}"
        XCODE_ATTRIBUTE_DEVELOPMENT_TEAM "${PS1IOS_TEAM}"
        XCODE_ATTRIBUTE_CODE_SIGN_STYLE "Automatic"
        XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY "Apple Development"
        XCODE_ATTRIBUTE_IPHONEOS_DEPLOYMENT_TARGET "16.0"
        XCODE_ATTRIBUTE_TARGETED_DEVICE_FAMILY "1,2"
        XCODE_ATTRIBUTE_ENABLE_BITCODE "NO"
        XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS "${PS1IOS_DIR}/App.entitlements"
        XCODE_ATTRIBUTE_GCC_OPTIMIZATION_LEVEL "3"
        XCODE_ATTRIBUTE_LLVM_LTO "YES_THIN"
        XCODE_ATTRIBUTE_DEAD_CODE_STRIPPING "YES")
    if(PS1IOS_GAMEDATA)
        target_sources(psx-runtime PRIVATE "${PS1IOS_GAMEDATA}")
        set_source_files_properties("${PS1IOS_GAMEDATA}" PROPERTIES MACOSX_PACKAGE_LOCATION Resources)
    endif()
    if(PS1IOS_MOLTENVK)
        # SDL_Vulkan_LoadLibrary(NULL) on iOS loads MoltenVK from the app's Frameworks/.
        set_target_properties(psx-runtime PROPERTIES
            XCODE_EMBED_FRAMEWORKS "${PS1IOS_MOLTENVK}"
            XCODE_EMBED_FRAMEWORKS_CODE_SIGN_ON_COPY ON
            XCODE_ATTRIBUTE_LD_RUNPATH_SEARCH_PATHS "@executable_path/Frameworks")
    endif()
endfunction()

cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL ps1ios_finalize)
