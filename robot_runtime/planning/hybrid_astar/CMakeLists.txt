cmake_minimum_required(VERSION 3.16)
project(hybrid_astar LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(GNUInstallDirs)

find_package(ament_cmake QUIET)
find_package(Boost REQUIRED)
find_package(ompl REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgcodecs)

set(HYBRID_ASTAR_SOURCES
    src/algorithm.cpp
    src/node2d.cpp
    src/node3d.cpp
    src/collisiondetection.cpp
    src/planner.cpp
    src/smoother.cpp
    src/dubins.cpp
    src/dynamicvoronoi.cpp
    src/bucketedqueue.cpp
)

add_library(hybrid_astar_core STATIC ${HYBRID_ASTAR_SOURCES})
add_library(HybridAStar::core ALIAS hybrid_astar_core)

target_compile_options(hybrid_astar_core PRIVATE -Wall -Wextra -Wpedantic)
target_include_directories(hybrid_astar_core
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PUBLIC
    ${Boost_INCLUDE_DIRS}
    ${OMPL_INCLUDE_DIRS}
  PRIVATE
    ${OpenCV_INCLUDE_DIRS}
)
target_link_libraries(hybrid_astar_core
  PUBLIC
    ${OMPL_LIBRARIES}
    ${OpenCV_LIBRARIES}
)

set(HYBRID_ASTAR_DEFAULT_MAP_PATH
  "${CMAKE_CURRENT_SOURCE_DIR}/maps/empty_80x80.png"
)
if(ament_cmake_FOUND)
  set(HYBRID_ASTAR_DEFAULT_MAP_PATH
    "${CMAKE_INSTALL_PREFIX}/share/${PROJECT_NAME}/maps/empty_80x80.png"
  )
endif()

add_executable(hybrid_astar_plan src/main.cpp)
target_compile_options(hybrid_astar_plan PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(hybrid_astar_plan PRIVATE
  HYBRID_ASTAR_DEFAULT_MAP_PATH="${HYBRID_ASTAR_DEFAULT_MAP_PATH}"
)
target_link_libraries(hybrid_astar_plan PRIVATE HybridAStar::core)

if(ament_cmake_FOUND)
  install(
    TARGETS hybrid_astar_core hybrid_astar_plan
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION lib/${PROJECT_NAME}
  )
else()
  install(
    TARGETS hybrid_astar_core hybrid_astar_plan
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
  )
endif()
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(
  FILES maps/empty_80x80.png
  DESTINATION ${CMAKE_INSTALL_DATADIR}/hybrid_astar/maps
)

if(ament_cmake_FOUND)
  ament_package()
endif()
