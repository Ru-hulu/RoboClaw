#include <cmath>
#include <mutex>
#include <string>

#include <gazebo/common/Events.hh>
#include <gazebo/common/Plugin.hh>
#include <gazebo/physics/Model.hh>
#include <gazebo/physics/World.hh>
#include <gazebo_ros/node.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <ignition/math/Pose3.hh>
#include <rclcpp/rclcpp.hpp>

namespace openarm2_minimal_gazebo
{
class RigidCmdVelPlugin : public gazebo::ModelPlugin
{
public:
  void Load(gazebo::physics::ModelPtr model, sdf::ElementPtr sdf) override
  {
    model_ = model;
    node_ = gazebo_ros::Node::Get(sdf);

    command_topic_ = sdf->Get<std::string>("command_topic", "cmd_vel").first;
    command_timeout_sec_ = sdf->Get<double>("command_timeout", 0.5).first;
    fixed_z_ = sdf->Get<double>("fixed_z", model_->WorldPose().Pos().Z()).first;

    pose_ = model_->WorldPose();
    pose_.Pos().Z(fixed_z_);
    last_update_time_ = model_->GetWorld()->SimTime();
    last_command_time_ = last_update_time_;

    command_subscription_ = node_->create_subscription<geometry_msgs::msg::Twist>(
      command_topic_,
      rclcpp::QoS(10),
      [this](geometry_msgs::msg::Twist::SharedPtr message)
      {
        std::lock_guard<std::mutex> lock(command_mutex_);
        command_ = *message;
        last_command_time_ = model_->GetWorld()->SimTime();
      });

    update_connection_ = gazebo::event::Events::ConnectWorldUpdateBegin(
      [this](const gazebo::common::UpdateInfo & info)
      {
        OnUpdate(info);
      });

    RCLCPP_INFO(
      node_->get_logger(),
      "Rigid cmd_vel plugin loaded for model [%s], topic [%s].",
      model_->GetName().c_str(),
      command_topic_.c_str());
  }

private:
  void OnUpdate(const gazebo::common::UpdateInfo & info)
  {
    const auto now = info.simTime;
    const double dt = (now - last_update_time_).Double();
    last_update_time_ = now;
    if (dt <= 0.0) {
      return;
    }

    geometry_msgs::msg::Twist command;
    {
      std::lock_guard<std::mutex> lock(command_mutex_);
      command = command_;
      if (
        command_timeout_sec_ > 0.0 &&
        (now - last_command_time_).Double() > command_timeout_sec_)
      {
        command.linear.x = 0.0;
        command.linear.y = 0.0;
        command.linear.z = 0.0;
        command.angular.x = 0.0;
        command.angular.y = 0.0;
        command.angular.z = 0.0;
      }
    }

    const double yaw = pose_.Rot().Yaw();
    const double cos_yaw = std::cos(yaw);
    const double sin_yaw = std::sin(yaw);
    const double world_vx = cos_yaw * command.linear.x - sin_yaw * command.linear.y;
    const double world_vy = sin_yaw * command.linear.x + cos_yaw * command.linear.y;
    const double next_yaw = yaw + command.angular.z * dt;

    pose_.Pos().X(pose_.Pos().X() + world_vx * dt);
    pose_.Pos().Y(pose_.Pos().Y() + world_vy * dt);
    pose_.Pos().Z(fixed_z_);
    pose_.Rot() = ignition::math::Quaterniond(0.0, 0.0, next_yaw);

    model_->SetWorldPose(pose_, true, true);
    model_->SetLinearVel(ignition::math::Vector3d(world_vx, world_vy, 0.0));
    model_->SetAngularVel(ignition::math::Vector3d(0.0, 0.0, command.angular.z));
  }

  gazebo::physics::ModelPtr model_;
  gazebo_ros::Node::SharedPtr node_;
  gazebo::event::ConnectionPtr update_connection_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr command_subscription_;
  gazebo::common::Time last_update_time_;
  gazebo::common::Time last_command_time_;
  ignition::math::Pose3d pose_;
  std::mutex command_mutex_;
  geometry_msgs::msg::Twist command_;
  std::string command_topic_;
  double command_timeout_sec_{0.5};
  double fixed_z_{0.0};
};

GZ_REGISTER_MODEL_PLUGIN(RigidCmdVelPlugin)
}  // namespace openarm2_minimal_gazebo
