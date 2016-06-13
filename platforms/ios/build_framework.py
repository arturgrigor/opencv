#!/usr/bin/env python
"""
The script builds OpenCV.framework for iOS.
The built framework is universal, it can be used to build app and run it on either iOS simulator or real device.

Usage:
    ./build_framework.py <outputdir>

By cmake conventions (and especially if you work with OpenCV repository),
the output dir should not be a subdirectory of OpenCV source tree.

Script will create <outputdir>, if it's missing, and a few its subdirectories:

    <outputdir>
        build/
            iPhoneOS-*/
               [cmake-generated build tree for an iOS device target]
            iPhoneSimulator-*/
               [cmake-generated build tree for iOS simulator]
        opencv2.framework/
            [the framework content]

The script should handle minor OpenCV updates efficiently
- it does not recompile the library from scratch each time.
However, opencv2.framework directory is erased and recreated on each run.
"""

from __future__ import print_function
import glob, re, os, os.path, shutil, string, sys, exceptions, subprocess, argparse
from subprocess import check_call, check_output, CalledProcessError

def run(cmd):
    try:
        print("Executing: " + cmd, file=sys.stderr)
        retcode = subprocess.call(cmd, shell=True)
        if retcode < 0:
            raise Exception("Child was terminated by signal:", -retcode)
        elif retcode > 0:
            raise Exception("Child returned:", retcode)
    except OSError as e:
        raise Exception("Execution failed:", e)

def execute(cmd, cwd = None):
    print("Executing: %s in %s" % (cmd, cwd), file=sys.stderr)
    retcode = check_call(cmd, cwd = cwd)
    if retcode != 0:
        raise Exception("Child returned:", retcode)

def build_opencv(srcroot, buildroot, target, arch, extra_cmake_flags):
    "builds OpenCV for device or simulator"

    builddir = os.path.join(buildroot, target + '-' + arch)
    if not os.path.isdir(builddir):
        os.makedirs(builddir)
    currdir = os.getcwd()
    os.chdir(builddir)
    # for some reason, if you do not specify CMAKE_BUILD_TYPE, it puts libs to "RELEASE" rather than "Release"
    cmakeargs = ("-GXcode " +
                "-DCMAKE_BUILD_TYPE=Release " +
                "-DCMAKE_TOOLCHAIN_FILE=%s/platforms/ios/cmake/Toolchains/Toolchain-%s_Xcode.cmake " +
                "-DCMAKE_C_FLAGS=\"-Wno-implicit-function-declaration\" " +
                "-DCMAKE_INSTALL_PREFIX=install") % (srcroot, target)

    if arch.startswith("armv"):
        cmakeargs += " -DENABLE_NEON=ON"

    cmakeargs += reduce((lambda a, b: " " + a + " " + b), extra_cmake_flags)

    # if cmake cache exists, just rerun cmake to update OpenCV.xcodeproj if necessary
    if os.path.isfile(os.path.join(builddir, "CMakeCache.txt")):
        run("cmake %s ." % (cmakeargs,))
    else:
        run("cmake %s %s" % (cmakeargs, srcroot))

    run("xcodebuild IPHONEOS_DEPLOYMENT_TARGET=6.0 -parallelizeTargets ARCHS=%s -jobs 8 -sdk %s -configuration Release -target ALL_BUILD" % (arch, target.lower()))
    run("xcodebuild IPHONEOS_DEPLOYMENT_TARGET=6.0 ARCHS=%s -sdk %s -configuration Release -target install install" % (arch, target.lower()))
    os.chdir(currdir)

def mergeLibs(dstroot):
    # find the list of targets (basically, ["iPhoneOS", "iPhoneSimulator"])
    targetlist = glob.glob(os.path.join(dstroot, "build", "*"))

    for builddir in targetlist:
        res = os.path.join(builddir, "lib", "Release", "libopencv_merged")
        libs = glob.glob(os.path.join(builddir, "lib", "Release", "*.a"))
        print("Merging libraries:\n\t%s" % "\n\t".join(libs), file=sys.stderr)
        execute(["libtool", "-static", "-o", res] + libs)

def put_framework_together(srcroot, dstroot):
    "constructs the framework directory after all the targets are built"

    name = "opencv2"
    libname = "libopencv_merged"

    # find the list of targets (basically, ["iPhoneOS", "iPhoneSimulator"])
    targetlist = glob.glob(os.path.join(dstroot, "build", "*"))
    targetlist = [os.path.basename(t) for t in targetlist]

    # set the current dir to the dst root
    currdir = os.getcwd()
    framework_dir = dstroot + "/opencv2.framework"
    if os.path.isdir(framework_dir):
        shutil.rmtree(framework_dir)
    os.makedirs(framework_dir)
    os.chdir(framework_dir)

    # form the directory tree
    dstdir = "Versions/A"
    os.makedirs(dstdir + "/Resources")

    tdir0 = "../build/" + targetlist[0]
    # copy headers
    shutil.copytree(tdir0 + "/install/include/opencv2", dstdir + "/Headers")

    # make universal static lib
    libs = [os.path.join("../build/" + d, "lib", "Release", libname) for d in targetlist]
    lipocmd = ["lipo", "-create"]
    lipocmd.extend(libs)
    lipocmd.extend(["-o", os.path.join(dstdir, name)])
    print("Creating universal library from:\n\t%s" % "\n\t".join(libs), file=sys.stderr)
    execute(lipocmd)

    # copy Info.plist
    shutil.copyfile(tdir0 + "/ios/Info.plist", dstdir + "/Resources/Info.plist")

    # make symbolic links
    os.symlink("A", "Versions/Current")
    os.symlink("Versions/Current/Headers", "Headers")
    os.symlink("Versions/Current/Resources", "Resources")
    os.symlink("Versions/Current/opencv2", "opencv2")


def build_framework(srcroot, dstroot, supportedarchs, excluded_modules):
    "main function to do all the work"

    extra_cmake_flags = list(map((lambda e: "-DBUILD_opencv_"+e+"=OFF"), excluded_modules)) if excluded_modules is not None else []
    for t in supportedarchs:
        build_opencv(srcroot, os.path.join(dstroot, "build"), t[1], t[0], extra_cmake_flags)

    mergeLibs(dstroot)
    put_framework_together(srcroot, dstroot)


if __name__ == "__main__":
    allarchs = [
        ("armv7", "iPhoneOS"),
        ("armv7s", "iPhoneOS"),
        ("arm64", "iPhoneOS"),
        ("i386", "iPhoneSimulator"),
        ("x86_64", "iPhoneSimulator"),
    ]
    archs = list(map((lambda e: e[0]), allarchs))
    archs = reduce((lambda a, b: a + "," + b), archs)
    folder = os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), "../.."))
    parser = argparse.ArgumentParser(description='The script builds OpenCV.framework for iOS.')
    parser.add_argument('out', metavar='OUTDIR', help='folder to put built framework')
    parser.add_argument('--archs', metavar='ARCHS', default=archs, help='the supported architectures (default is all "armv7,armv7s,arm64,i386,x86_64")')
    parser.add_argument('--excluded_modules', default=None, help='the excluded modules (default is "None")')
    args = parser.parse_args()
    inputarchs = None if args.archs is None else [item for item in args.archs.split(',')]
    supportedarchs = [e for e in allarchs if e[0] in inputarchs]
    excluded_modules = None if args.excluded_modules is None else [item for item in args.excluded_modules.split(',')]
    print("Building only for " + str(inputarchs) + "...")
    if excluded_modules is not None:
        print("Excluding the modules " + str(excluded_modules))

    try:
        build_framework(os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), "../..")), os.path.abspath(args.out), supportedarchs, excluded_modules)
    except Exception as e:
        print("="*60, file=sys.stderr)
        print("ERROR: %s" % e, file=sys.stderr)
        print("="*60, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
