execute_process(COMMAND "/home/robond/Desktop/catkin_ws/build/RL-Quadcopter/quad_controller_rl/catkin_generated/python_distutils_install.sh" RESULT_VARIABLE res)

if(NOT res EQUAL 0)
  message(FATAL_ERROR "execute_process(/home/robond/Desktop/catkin_ws/build/RL-Quadcopter/quad_controller_rl/catkin_generated/python_distutils_install.sh) returned error code ")
endif()
